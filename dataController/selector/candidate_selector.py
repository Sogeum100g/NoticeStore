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
    api_key = os.getenv("OPEN_AI_API_KEY_SELECT_API")
    if not api_key:
        raise RuntimeError("OPEN_AI_API_KEY_SELECT_API 환경 변수가 비어 있습니다.")

    client = OpenAI(api_key=api_key)
    compact_api_data = json.dumps(optimized_candidates, ensure_ascii=False, separators=(",", ":"))
    prompt = RAW_PROMPT.format(api_list=compact_api_data)

    response = client.responses.parse(
        model="gpt-5-nano",
        input=prompt,
        text_format=CandidateSelectionResponse,
    )

    parsed = response.output_parsed
    if parsed is None:
        raise ValueError("OpenAI 응답에서 구조화된 후보 선택 결과를 얻지 못했습니다.")

    usage = response.usage
    in_tokens = usage.input_tokens if usage else 0
    out_tokens = usage.output_tokens if usage else 0
    cost_in = (in_tokens / 1_000_000) * 0.05 * 1350
    cost_out = (out_tokens / 1_000_000) * 0.40 * 1350
    total_krw = cost_in + cost_out

    logger.info("OpenAI API 호출 완료 (입력 데이터 개수: %d)", len(optimized_candidates))
    logger.info(
        "📊 [GPT-5 nano] API Selection | Tokens: (In:%s / Out:%s) | Cost: ₩%.4f",
        in_tokens,
        out_tokens,
        total_krw,
    )
    result = parsed.model_dump()
    result["_usage"] = {
        "input_tokens": in_tokens,
        "output_tokens": out_tokens,
        "cost": total_krw,
    }
    return result


async def select_with_llm(
    llm_candidates: List[Dict[str, Any]],
    llm_reason: str,
) -> Optional[Dict[str, Any]]:
    optimized_candidates = _optimize_for_llm(llm_candidates)
    logger.info("🤖 [LLM 호출] GPT-5 nano를 이용한 핵심 API 선별 작업 시작 | reason=%s", llm_reason)

    try:
        response_data = await asyncio.to_thread(_call_openai_select_candidate, optimized_candidates)
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
        logger.warning("⚠️ GPT-5 nano 선택 실패, 규칙 기반 fallback을 사용합니다.", exc_info=True)
        fallback = dict(llm_candidates[0])
        fallback["selection_mode"] = "fallback_rule"
        fallback["selection_reason"] = "GPT-5 nano 선택 실패로 규칙 기반 최상위 후보를 fallback 선택했습니다."
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
