import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

try:
    from .candidate_ranker import build_candidate_pool, rank_candidates
except ImportError:  # pragma: no cover
    from dataController.selector.candidate_ranker import build_candidate_pool, rank_candidates

logger = logging.getLogger(__name__)

CURRENT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = CURRENT_DIR / "prompt_data.yaml"

SUPPORTED_LLM_PROVIDERS = {"openai", "gemini"}
USD_TO_KRW = 1350
OPENAI_INPUT_USD_PER_MILLION = 0.40
OPENAI_OUTPUT_USD_PER_MILLION = 1.60
GEMINI_INPUT_USD_PER_MILLION = 0.30
GEMINI_OUTPUT_USD_PER_MILLION = 2.50

load_dotenv()

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

RAW_PROMPT = config["prompts"]["api_selector"]
LLM_TOP_K = 4
RULE_ONLY_SINGLE_THRESHOLD = 12
RULE_ONLY_CLEAR_WINNER_SCORE = 22
RULE_ONLY_CLEAR_WINNER_GAP = 6
RULE_ONLY_STRONG_DATA_GAP = 4


class CandidateSelectionResponse(BaseModel):
    index: int = Field(description="선택한 API의 api_index. 유효 후보가 없으면 -1")
    reason: str = Field(description="이 API를 핵심 데이터로 판단한 명확한 근거")


def _get_llm_provider() -> str:
    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    if provider == "google":
        provider = "gemini"
    if provider not in SUPPORTED_LLM_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_LLM_PROVIDERS))
        raise RuntimeError(
            f"LLM_PROVIDER는 다음 값 중 하나여야 합니다: {supported} (현재: {provider!r})"
        )
    return provider


def _get_openai_model() -> str:
    model = os.getenv("OPENAI_MODEL")
    if not model:
        raise RuntimeError("OPENAI_MODEL 환경 변수가 비어 있습니다.")
    # 과거 OpenAI 호환 Proxy에서 사용한 provider prefix는 OpenAI API 모델
    # 식별자가 아니므로 직접 호출 시 제거한다.
    return model.removeprefix("openai/")


def _get_gemini_model() -> str:
    model = os.getenv("GEMINI_MODEL")
    if not model:
        raise RuntimeError("GEMINI_MODEL 환경 변수가 비어 있습니다.")
    return model.removeprefix("models/")


def _get_active_provider_and_model() -> Tuple[str, str]:
    provider = _get_llm_provider()
    if provider == "openai":
        return provider, _get_openai_model()
    return provider, _get_gemini_model()


def _build_candidate_prompt(optimized_candidates: List[Dict[str, Any]]) -> str:
    compact_api_data = json.dumps(
        optimized_candidates,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return RAW_PROMPT.format(api_list=compact_api_data)


def _estimate_cost_krw(
    input_tokens: int,
    output_tokens: int,
    input_usd_per_million: float,
    output_usd_per_million: float,
) -> float:
    cost_in = (input_tokens / 1_000_000) * input_usd_per_million * USD_TO_KRW
    cost_out = (output_tokens / 1_000_000) * output_usd_per_million * USD_TO_KRW
    return cost_in + cost_out


def classify_candidate_decision(
    ranked_candidates: List[Dict[str, Any]],
) -> Tuple[str, str]:
    """Return accept_rule, defer_to_llm, or reject_or_observe_more."""
    if not ranked_candidates:
        return "reject_or_observe_more", "유효 후보가 없습니다."

    top = ranked_candidates[0]
    top_score = top.get("score", 0)
    top_features = top.get("features") or {}
    has_records = bool(top_features.get("has_repeated_records"))

    if (
        top_features.get("looks_like_static_asset")
        or top_features.get("looks_like_telemetry")
        or top_features.get("looks_like_non_content")
    ):
        return "reject_or_observe_more", "상위 후보가 정적 자원 또는 telemetry 잡음입니다."

    if len(ranked_candidates) == 1:
        if has_records and top_score >= RULE_ONLY_SINGLE_THRESHOLD:
            return "accept_rule", "단일 후보가 반복 레코드와 절대 점수 gate를 통과했습니다."
        if has_records:
            return "defer_to_llm", "단일 후보의 데이터성은 있으나 절대 신뢰도가 낮습니다."
        return "reject_or_observe_more", "단일 후보에 반복 게시물 증거가 없습니다."

    top2_score = ranked_candidates[1].get("score", 0)
    gap = top_score - top2_score
    if (
        has_records
        and top_score >= RULE_ONLY_CLEAR_WINNER_SCORE
        and gap >= RULE_ONLY_CLEAR_WINNER_GAP
    ):
        return "accept_rule", f"1위 후보가 절대 점수와 점수 차 gate를 통과했습니다(gap={gap})."

    if (
        has_records
        and top_features.get("has_title_key")
        and (
            top_features.get("is_jsonp_like")
            or (
                top_features.get("is_json_like")
                and top_features.get("has_list_key")
            )
        )
        and gap >= RULE_ONLY_STRONG_DATA_GAP
    ):
        return "accept_rule", "구조화 목록 후보가 데이터성과 상대 우위 gate를 통과했습니다."

    if any(
        (item.get("features") or {}).get("has_repeated_records")
        for item in ranked_candidates
    ):
        return "defer_to_llm", f"유효한 데이터 후보는 있으나 규칙상 우위가 불충분합니다(gap={gap})."

    return "reject_or_observe_more", "반복 게시물 증거가 있는 후보가 없습니다."


def should_use_llm(ranked_candidates: List[Dict[str, Any]]) -> Tuple[bool, str]:
    decision, reason = classify_candidate_decision(ranked_candidates)
    return decision == "defer_to_llm", reason


def select_rule_based(ranked_candidates: List[Dict[str, Any]], reason: str) -> Optional[Dict[str, Any]]:
    if not ranked_candidates:
        return None
    selected = dict(ranked_candidates[0])
    selected["selection_mode"] = "rule_based"
    selected["selection_reason"] = reason
    return selected


def _optimize_for_llm(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    optimized: List[Dict[str, Any]] = []
    for item in candidates:
        payload = item.get("payload") or {}
        payload_keys = list(payload.keys())[:10] if isinstance(payload, dict) else []
        features = item.get("features") or {}
        optimized.append(
            {
                "api_index": item.get("api_index"),
                "method_type": item.get("method_type"),
                "type": item.get("type"),
                "source_kind": item.get("source_kind"),
                "api_url": item.get("api_url"),
                "content_type": item.get("content_type"),
                "score": item.get("score"),
                "data_key_hits": item.get("data_key_hits", [])[:8],
                "body_shape": item.get("body_shape"),
                "has_callback_param": item.get("has_callback_param"),
                "payload_keys": payload_keys,
                "feature_summary": {
                    "is_exact_target": features.get("is_exact_target"),
                    "is_same_host": features.get("is_same_host"),
                    "has_title_key": features.get("has_title_key"),
                    "has_date_key": features.get("has_date_key"),
                    "has_list_key": features.get("has_list_key"),
                    "has_total_count": features.get("has_total_count"),
                    "has_repeated_records": features.get("has_repeated_records"),
                    "semantic_record_count": features.get("semantic_record_count"),
                    "title_date_pair_count": features.get("title_date_pair_count"),
                    "has_notice_terms": features.get("has_notice_terms"),
                    "looks_like_non_content": features.get("looks_like_non_content"),
                    "is_json_like": features.get("is_json_like"),
                    "is_jsonp_like": features.get("is_jsonp_like"),
                    "legacy_endpoint_hint": features.get("legacy_endpoint_hint"),
                },
                "sample": (item.get("sample") or "")[:240],
            }
        )
    return optimized


def _call_openai_select_candidate(optimized_candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    api_key = os.getenv("OPEN_AI_API_KEY_SELECT_API") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPEN_AI_API_KEY_SELECT_API 또는 OPENAI_API_KEY 환경 변수가 비어 있습니다."
        )

    model = _get_openai_model()

    client = OpenAI(api_key=api_key)
    prompt = _build_candidate_prompt(optimized_candidates)

    response = client.chat.completions.parse(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format=CandidateSelectionResponse,
    )

    parsed = response.choices[0].message.parsed if response.choices else None
    if parsed is None:
        raise ValueError("OpenAI 응답에서 구조화된 후보 선택 결과를 얻지 못했습니다.")

    usage = response.usage
    in_tokens = usage.prompt_tokens if usage else 0
    out_tokens = usage.completion_tokens if usage else 0
    total_krw = _estimate_cost_krw(
        in_tokens,
        out_tokens,
        OPENAI_INPUT_USD_PER_MILLION,
        OPENAI_OUTPUT_USD_PER_MILLION,
    )

    logger.info("OpenAI API 직접 호출 완료 (입력 데이터 개수: %d)", len(optimized_candidates))
    logger.info(
        "📊 [%s] API Selection | Tokens: (In:%s / Out:%s) | Estimated Cost: ₩%.4f",
        model,
        in_tokens,
        out_tokens,
        total_krw,
    )
    result = parsed.model_dump()
    result["_usage"] = {
        "provider": "openai",
        "model": model,
        "input_tokens": in_tokens,
        "output_tokens": out_tokens,
        "cost": total_krw,
    }
    return result


def _create_gemini_client(api_key: str) -> Any:
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover - production dependency guard
        raise RuntimeError(
            "Gemini 사용에는 google-genai 패키지가 필요합니다. requirements.txt를 설치하세요."
        ) from exc
    return genai.Client(api_key=api_key)


def _call_gemini_select_candidate(optimized_candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY_SELECT_API") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY_SELECT_API 또는 GEMINI_API_KEY 환경 변수가 비어 있습니다."
        )

    model = _get_gemini_model()
    client = _create_gemini_client(api_key)
    prompt = _build_candidate_prompt(optimized_candidates)

    interaction = client.interactions.create(
        model=model,
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": CandidateSelectionResponse.model_json_schema(),
        },
    )

    output_text = getattr(interaction, "output_text", None)
    if not output_text:
        raise ValueError("Gemini 응답에서 구조화된 후보 선택 결과를 얻지 못했습니다.")
    parsed = CandidateSelectionResponse.model_validate_json(output_text)

    usage = getattr(interaction, "usage", None)
    in_tokens = int(getattr(usage, "total_input_tokens", 0) or 0)
    out_tokens = int(getattr(usage, "total_output_tokens", 0) or 0)
    thought_tokens = int(getattr(usage, "total_thought_tokens", 0) or 0)
    billable_output_tokens = out_tokens + thought_tokens
    total_krw = _estimate_cost_krw(
        in_tokens,
        billable_output_tokens,
        GEMINI_INPUT_USD_PER_MILLION,
        GEMINI_OUTPUT_USD_PER_MILLION,
    )

    logger.info("Gemini API 직접 호출 완료 (입력 데이터 개수: %d)", len(optimized_candidates))
    logger.info(
        "📊 [%s] API Selection | Tokens: (In:%s / Out:%s / Thought:%s) | Estimated Cost: ₩%.4f",
        model,
        in_tokens,
        out_tokens,
        thought_tokens,
        total_krw,
    )
    result = parsed.model_dump()
    result["_usage"] = {
        "provider": "gemini",
        "model": model,
        "input_tokens": in_tokens,
        "output_tokens": out_tokens,
        "thought_tokens": thought_tokens,
        "cost": total_krw,
    }
    return result


def _call_llm_select_candidate(optimized_candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    provider = _get_llm_provider()
    if provider == "openai":
        return _call_openai_select_candidate(optimized_candidates)
    return _call_gemini_select_candidate(optimized_candidates)


async def select_with_llm(
    llm_candidates: List[Dict[str, Any]],
    llm_reason: str,
) -> Optional[Dict[str, Any]]:
    optimized_candidates = _optimize_for_llm(llm_candidates)
    try:
        provider, model = _get_active_provider_and_model()
    except RuntimeError:
        provider, model = "LLM", "unconfigured model"
    logger.info(
        "🤖 [LLM 호출] %s/%s를 이용한 핵심 API 선별 작업 시작 | reason=%s",
        provider,
        model,
        llm_reason,
    )

    try:
        response_data = await asyncio.to_thread(_call_llm_select_candidate, optimized_candidates)
        selected_index = int(response_data.get("index"))
        selection_reason = response_data.get("reason", "")
        if selected_index == -1:
            logger.info("🛑 LLM이 입력 후보 중 유효한 목록 데이터가 없다고 판정했습니다.")
            return None

        selected_candidate = next(
            (item for item in llm_candidates if item.get("api_index") == selected_index),
            None,
        )
        if selected_candidate is None:
            raise ValueError(f"선택된 index {selected_index}에 해당하는 후보가 없습니다.")

        selected = dict(selected_candidate)
        selected["selection_mode"] = "llm"
        selected["selection_reason"] = selection_reason or llm_reason
        selected["llm_gate_reason"] = llm_reason
        selected["_llm_usage"] = response_data.get("_usage") or {}
        return selected

    except Exception:
        logger.warning(
            "⚠️ %s/%s 선택 실패, 규칙 기반 fallback을 사용합니다.",
            provider,
            model,
            exc_info=True,
        )
        fallback = dict(llm_candidates[0])
        fallback["selection_mode"] = "fallback_rule"
        fallback["selection_reason"] = (
            f"{provider}/{model} 선택 실패로 규칙 기반 최상위 후보를 fallback 선택했습니다."
        )
        fallback["llm_gate_reason"] = llm_reason
        return fallback


async def prioritize_candidates(
    candidates: List[Dict[str, Any]],
    target_url: str,
) -> List[Dict[str, Any]]:
    if not candidates:
        return []

    ranked_candidates = rank_candidates(candidates, target_url)
    if not ranked_candidates:
        return []

    llm_candidates = build_candidate_pool(
        ranked_candidates,
        target_url,
        limit=LLM_TOP_K,
    )

    decision, decision_reason = classify_candidate_decision(llm_candidates)
    use_llm = decision == "defer_to_llm"
    logger.info(
        "🧭 후보 3방향 판정 | decision=%s | reason=%s",
        decision,
        decision_reason,
    )

    if decision == "reject_or_observe_more":
        return []
    if decision == "accept_rule":
        selected = select_rule_based(ranked_candidates, decision_reason)
    else:
        selected = await select_with_llm(llm_candidates, decision_reason)
        if selected is None:
            return []

    selected["selection_decision"] = decision
    prioritized: List[Dict[str, Any]] = []
    seen_indexes = set()

    def add(item: Optional[Dict[str, Any]]) -> None:
        if not item:
            return
        index = item.get("api_index")
        if index in seen_indexes:
            return
        prioritized.append(item)
        seen_indexes.add(index)

    add(selected)
    for item in llm_candidates:
        add(item)
    for item in ranked_candidates:
        add(item)
    return prioritized


async def select_candidate(candidates: List[Dict[str, Any]], target_url: str) -> Optional[Dict[str, Any]]:
    prioritized = await prioritize_candidates(candidates, target_url)
    return prioritized[0] if prioritized else None
