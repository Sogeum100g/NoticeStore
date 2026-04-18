import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

CURRENT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = CURRENT_DIR / "prompt_data.yaml"

load_dotenv()

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

RAW_PROMPT = config["prompts"]["api_selector"]

NOTICE_HINTS = ("공지", "notice", "조회수", "첨부파일", "게시", "board", "title", "subject")
LIKELY_SOURCE_KIND_BONUS = {
    "document_html": 35,
    "xhr_json": 30,
    "graphql": 28,
    "form_post": 25,
    "post_json": 25,
    "xhr_html": 20,
}


def _score_candidate(candidate: Dict[str, Any], target_url: str) -> int:
    score = 0
    source_kind = candidate.get("source_kind", "")
    resource_type = candidate.get("type", "")
    method = candidate.get("method_type", "GET")
    api_url = candidate.get("api_url", "")
    sample = (candidate.get("sample") or "").lower()
    content_type = (candidate.get("content_type") or "").lower()

    score += LIKELY_SOURCE_KIND_BONUS.get(source_kind, 0)

    if resource_type in {"document", "fetch", "xhr"}:
        score += 10
    if method == "POST":
        score += 8
    if "json" in content_type:
        score += 6
    if "html" in content_type:
        score += 4

    target_host = urlparse(target_url).netloc
    candidate_host = urlparse(api_url).netloc
    if target_host and candidate_host and target_host == candidate_host:
        score += 10

    if any(hint in sample for hint in NOTICE_HINTS):
        score += 14

    if len(sample) >= 80:
        score += 4

    return score


def _prepare_llm_candidates(candidates: List[Dict[str, Any]], target_url: str, limit: int = 12) -> List[Dict[str, Any]]:
    ranked = sorted(
        candidates,
        key=lambda item: _score_candidate(item, target_url),
        reverse=True,
    )
    return ranked[:limit]


def _optimize_for_llm(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    optimized: List[Dict[str, Any]] = []
    for item in candidates:
        payload_keys = []
        payload = item.get("payload") or {}
        if isinstance(payload, dict):
            payload_keys = list(payload.keys())[:10]

        optimized.append(
            {
                "api_index": item.get("api_index"),
                "method_type": item.get("method_type"),
                "type": item.get("type"),
                "source_kind": item.get("source_kind"),
                "api_url": item.get("api_url"),
                "content_type": item.get("content_type"),
                "payload_keys": payload_keys,
                "sample": (item.get("sample") or "")[:220],
            }
        )
    return optimized


def _call_gemini_select_candidate(optimized_candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY_SELECT_API")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY_SELECT_API 환경 변수가 비어 있습니다.")

    client = genai.Client(api_key=api_key)
    compact_api_data = json.dumps(optimized_candidates, ensure_ascii=False, separators=(",", ":"))
    prompt = RAW_PROMPT.format(api_list=compact_api_data)

    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0,
            response_schema=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "index": types.Schema(
                        type=types.Type.INTEGER,
                        description="선택한 API의 api_index"
                    ),
                    "reason": types.Schema(
                        type=types.Type.STRING,
                        description="이 API를 핵심 데이터로 판단한 명확한 근거"
                    ),
                },
                required=["index", "reason"],
            ),
        ),
    )

    usage = response.usage_metadata
    in_tokens = usage.prompt_token_count
    out_tokens = usage.candidates_token_count
    cost_in = (in_tokens / 1_000_000) * 0.075 * 1350
    cost_out = (out_tokens / 1_000_000) * 0.30 * 1350
    total_krw = cost_in + cost_out

    logger.info("Gemini API 호출 완료 (입력 데이터 개수: %d)", len(optimized_candidates))
    logger.info(
        "📊 [Gemini 2.5 Flash Lite] API Selection | Tokens: (In:%s / Out:%s) | Cost: ₩%.4f",
        in_tokens,
        out_tokens,
        total_krw,
    )
    return json.loads(response.text)


async def select_candidate(candidates: List[Dict[str, Any]], target_url: str) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None

    ranked_candidates = _prepare_llm_candidates(candidates, target_url=target_url, limit=12)
    if not ranked_candidates:
        return None

    if len(ranked_candidates) == 1:
        only_candidate = dict(ranked_candidates[0])
        only_candidate["selection_reason"] = "후보가 1개뿐이어서 자동 선택했습니다."
        return only_candidate

    optimized_candidates = _optimize_for_llm(ranked_candidates)
    logger.info("🤖 [LLM 호출] Gemini를 이용한 핵심 API 선별 작업 시작")

    try:
        response_data = await asyncio.to_thread(_call_gemini_select_candidate, optimized_candidates)
        selected_index = int(response_data.get("index"))
        selection_reason = response_data.get("reason", "")
        if selected_index == -1:
            raise ValueError("LLM returned -1")

        selected_candidate = next(
            (item for item in ranked_candidates if item.get("api_index") == selected_index),
            None,
        )
        if selected_candidate is None:
            raise ValueError(f"선택된 index {selected_index}에 해당하는 후보가 없습니다.")

        selected = dict(selected_candidate)
        selected["selection_reason"] = selection_reason
        return selected

    except Exception:
        fallback = dict(ranked_candidates[0])
        fallback["selection_reason"] = "Gemini 선택 실패로 규칙 기반 최상위 후보를 fallback 선택했습니다."
        logger.warning("⚠️ Gemini 선택 실패, 규칙 기반 fallback을 사용합니다.", exc_info=True)
        return fallback
