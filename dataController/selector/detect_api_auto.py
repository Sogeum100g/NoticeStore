import asyncio
import datetime
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytz
import requests

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from repositories import notice_repo
from dataController.security.url_safety import (
    ResponseTooLargeError,
    UnsafeUrlError,
    safe_request,
    sanitize_outbound_headers,
    validate_public_url,
)
from dataController.selector.candidate_analyzer import analyze_candidate_body
from dataController.selector.candidate_collector import collect_candidates
from dataController.selector.candidate_ranker import build_candidate_pool, rank_candidates
from dataController.selector.candidate_selector import (
    LLM_TOP_K,
    classify_candidate_decision,
    prioritize_candidates,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

TEXTUAL_CONTENT_TYPE_HINTS = (
    "text/html", "application/json", "text/json", "application/xml", "text/xml",
    "text/plain", "application/javascript", "text/javascript", "application/x-javascript",
    "text/x-javascript", "application/graphql-response+json", "javasciprt"
)
MAX_VALIDATION_CANDIDATES = 8
MAX_VALIDATION_BODY_BYTES = 700_000
MAX_EVIDENCE_REASON_LENGTH = 500


def _redact_candidate_url(url: str) -> str:
    """Keep endpoint shape for review without persisting query values or fragments."""
    try:
        parsed = urlsplit(url or "")
        hostname = parsed.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        netloc = hostname
        if parsed.port is not None:
            netloc = f"{hostname}:{parsed.port}"
        query_keys = sorted(
            {
                key
                for key, _ in parse_qsl(
                    parsed.query,
                    keep_blank_values=True,
                )
            }
        )
        redacted_query = urlencode([(key, "") for key in query_keys])
        return urlunsplit(
            (
                parsed.scheme.lower(),
                netloc,
                parsed.path,
                redacted_query,
                "",
            )
        )
    except (TypeError, ValueError):
        return ""


def build_candidate_evidence(
    candidates: List[Dict[str, Any]],
    *,
    selected_candidate_index: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Build bounded, JSON-safe candidate telemetry for later calibration."""
    evidence: List[Dict[str, Any]] = []
    for rank, candidate in enumerate(
        candidates[:MAX_VALIDATION_CANDIDATES],
        start=1,
    ):
        raw_url = str(candidate.get("api_url") or "")
        redacted_url = _redact_candidate_url(raw_url)
        validation_reason = str(candidate.get("validation_reason") or "")
        if raw_url:
            validation_reason = validation_reason.replace(
                raw_url,
                redacted_url,
            )
        evidence.append(
            {
                "rank": rank,
                "api_index": candidate.get("api_index"),
                "selected": (
                    selected_candidate_index is not None
                    and candidate.get("api_index") == selected_candidate_index
                ),
                "method_type": candidate.get("method_type") or "GET",
                "source_kind": candidate.get("source_kind"),
                "endpoint": redacted_url,
                "url_hash": hashlib.sha256(
                    raw_url.encode("utf-8")
                ).hexdigest(),
                "score": candidate.get("score"),
                "score_reasons": list(
                    candidate.get("score_reasons") or []
                )[:20],
                "features": dict(candidate.get("features") or {}),
                "validation_status": (
                    candidate.get("validation_status")
                    or "not_replayed"
                ),
                "validation_reason": validation_reason[
                    :MAX_EVIDENCE_REASON_LENGTH
                ],
            }
        )
    return evidence


def _record_selection_failure(
    site_id: int,
    *,
    candidate_count: int,
    selection_decision: str,
    selection_reason: str,
    candidates: Optional[List[Dict[str, Any]]] = None,
    error_code: str,
) -> None:
    crawl_run_id = notice_repo.create_crawl_run(
        site_id,
        status="running",
        selection_mode="none",
        processing_mode="candidate_selection",
        candidate_count=candidate_count,
        selection_decision=selection_decision,
        selection_reason=selection_reason,
        candidate_evidence=build_candidate_evidence(candidates or []),
    )
    notice_repo.finish_crawl_run(
        crawl_run_id,
        status="failed",
        error_code=error_code,
        error_message=selection_reason,
    )


def save_site(url: str) -> Optional[int]:
    site_id = notice_repo.insert_site(
        site_url=url,
        created_at=datetime.datetime.now(pytz.timezone("Asia/Seoul")),
        submitted_url=url,
        crawl_status="pending",
        validation_status="valid",
    )
    logger.info("신규 사이트 정보 DB 저장 완료 (ID: %s): %s", site_id, url)
    return site_id


def save_api(api: Dict[str, Any], url: str) -> Optional[int]:
    site_id = notice_repo.select_site_id(url)
    api_id = notice_repo.upsert_api_for_site(
        site_id=site_id,
        method_type=api.get("method_type"),
        api_url=api.get("api_url"),
        headers=api.get("headers"),
        payload=api.get("payload"),
        last_hash=None,
        extractor_config=api.get("extractor_config"),
        schema_hash=api.get("schema_hash"),
        processing_status=api.get("processing_status"),
        extractor_confidence=api.get("extractor_confidence"),
    )
    if api_id:
        logger.info("검증 완료 API 정보 DB 저장 완료 (ID: %s)", api_id)
    return api_id


def _build_validation_headers(candidate: Dict[str, Any]) -> Dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/json,application/xml,text/javascript;q=0.9,*/*;q=0.8",
    }

    request_headers = candidate.get("headers") or {}
    for key in ("Referer", "Origin", "X-Requested-With", "Accept-Language"):
        value = request_headers.get(key) or request_headers.get(key.lower())
        if value:
            headers[key] = value
    return sanitize_outbound_headers(headers)


def _sync_validate_candidate(candidate: Dict[str, Any]) -> Tuple[str, str]:
    api_url = candidate.get("api_url")
    method = (candidate.get("method_type") or "GET").upper()
    source_kind = candidate.get("source_kind") or "unknown"
    payload_format = candidate.get("payload_format") or "query_only"
    body_payload = candidate.get("body_payload")
    if body_payload is None and method == "POST":
        body_payload = candidate.get("payload")
        request_content_type = ""
        for key, value in (candidate.get("headers") or {}).items():
            if key.lower() == "content-type":
                request_content_type = str(value).lower()
                break
        if "json" in request_content_type:
            payload_format = "json"
        elif isinstance(body_payload, dict):
            payload_format = "form"

    if not api_url:
        return "hard_failed", "api_url이 비어 있어 재현 검증이 불가능합니다."
    if method not in {"GET", "POST"}:
        return "soft_failed", f"현재 검증기는 {method} 메서드를 직접 재현하지 않습니다."

    headers = _build_validation_headers(candidate)
    body_bytes = None

    if method == "POST":
        if payload_format == "json" and isinstance(body_payload, dict):
            body_bytes = json.dumps(body_payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=UTF-8"
        elif payload_format in {"form", "query_only"} and isinstance(body_payload, dict):
            body_bytes = urlencode(body_payload, doseq=True).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        elif payload_format == "raw" and isinstance(body_payload, dict) and body_payload.get("_raw"):
            body_bytes = str(body_payload["_raw"]).encode("utf-8")
            headers["Content-Type"] = "text/plain; charset=UTF-8"

    try:
        session = requests.Session()
        request_kwargs: Dict[str, Any] = {}
        if method == "POST":
            if payload_format == "json" and isinstance(body_payload, dict):
                request_kwargs["json"] = body_payload
                request_kwargs["data"] = None
            else:
                request_kwargs["data"] = body_bytes

        response = safe_request(
            session,
            method,
            api_url,
            headers=headers,
            timeout=12,
            max_response_bytes=MAX_VALIDATION_BODY_BYTES,
            **request_kwargs,
        )
        try:
            content_type = response.headers.get("Content-Type", "").lower()
            if not response.encoding:
                response.encoding = response.apparent_encoding or "utf-8"
            text = response.text

            is_textual = any(hint in content_type for hint in TEXTUAL_CONTENT_TYPE_HINTS) or not content_type
            if response.status_code != 200 or not is_textual or len(text.strip()) < 80:
                return "soft_failed", (
                    f"응답 신호가 부족합니다. status={response.status_code}, "
                    f"content-type={content_type}, body_len={len(text.strip())}"
                )

            head = text.lstrip()[:120]
            if head.startswith("{"):
                body_shape = "json_object"
            elif head.startswith("["):
                body_shape = "json_array"
            elif head.startswith("<"):
                body_shape = "html"
            else:
                body_shape = candidate.get("body_shape") or "textual_other"

            analysis = analyze_candidate_body(
                text,
                body_shape=body_shape,
                content_type=content_type,
            )
            candidate["validation_analysis"] = analysis
            has_semantic_list = (
                analysis["has_repeated_records"]
                and "title" in analysis["data_key_hits"]
                and (
                    "date" in analysis["data_key_hits"]
                    or "list" in analysis["data_key_hits"]
                    or analysis["has_notice_terms"]
                )
            )
            if has_semantic_list:
                return (
                    "passed",
                    f"의미 검증 성공 ({method} {source_kind}, "
                    f"records={analysis['semantic_record_count']})",
                )

            return "semantic_failed", (
                "응답은 재현됐지만 반복되는 공지/게시물 레코드 증거가 없습니다. "
                f"kind={analysis['analysis_kind']}, "
                f"records={analysis['semantic_record_count']}, "
                f"keys={analysis['data_key_hits']}"
            )
        finally:
            response.close()
    except (UnsafeUrlError, ResponseTooLargeError) as e:
        return "hard_failed", f"보안 또는 자원 제한 검증 실패 ({e})"
    except requests.RequestException as e:
        if source_kind == "document_html" and method == "GET":
            return "hard_failed", f"직접 문서 GET 재현 실패 ({e})"
        return "soft_failed", f"재현 검증 중 HTTP 오류 발생 ({e})"
    except Exception as e:
        if source_kind == "document_html" and method == "GET":
            return "hard_failed", f"직접 문서 GET 재현 실패 ({e})"
        return "soft_failed", f"재현 검증 중 예외 발생 ({e})"


async def validate_candidate(candidate: Dict[str, Any]) -> Tuple[str, str]:
    return await asyncio.to_thread(_sync_validate_candidate, candidate)


async def find_api(target_url: str) -> Optional[Dict[str, Any]]:
    logger.info("🚀 [find_api 시작] 타겟 URL: %s", target_url)

    try:
        target_url = validate_public_url(target_url).url
    except UnsafeUrlError as exc:
        logger.warning("사용자 URL 보안 검증 실패: %s", exc)
        return None

    cached_api = notice_repo.select_api(target_url)
    if cached_api:
        logger.info("🔎 [DB 조회] 저장된 API를 의미 기준으로 재검증합니다.")
        cached_status, cached_reason = await validate_candidate(cached_api)
        logger.info("🔎 [캐시 검증] status=%s | %s", cached_status, cached_reason)
        if cached_status == "passed":
            notice_repo.update_site_crawl_state(
                cached_api["site_id"],
                crawl_status="active",
                validation_status="valid",
                validation_error=None,
            )
            cached_api["_pending_persistence"] = False
            return cached_api
        logger.warning("⚠️ 저장된 API가 의미 검증에 실패하여 후보를 다시 탐색합니다.")

    logger.info("🔍 [DB 조회] 저장된 API가 없습니다. 신규 사이트 등록 및 분석을 시작합니다.")
    site_id = notice_repo.select_site_id(target_url)
    if not site_id:
        site_id = save_site(target_url)

    if not site_id:
        logger.error("사이트 ID 확보 실패: %s", target_url)
        return None

    candidates = await collect_candidates(target_url)
    logger.info("수집된 API 후보 개수: %d", len(candidates))

    if not candidates:
        logger.warning("수집된 API 후보가 없습니다.")
        _record_selection_failure(
            site_id,
            candidate_count=0,
            selection_decision="reject_or_observe_more",
            selection_reason="수집된 API 후보가 없습니다.",
            error_code="NO_CANDIDATES",
        )
        notice_repo.update_site_crawl_state(
            site_id,
            crawl_status="failed",
            validation_status="valid",
            validation_error="수집된 API 후보가 없습니다.",
        )
        return None

    ranked_candidates = rank_candidates(candidates, target_url)
    replay_pool = build_candidate_pool(
        ranked_candidates,
        target_url,
        limit=MAX_VALIDATION_CANDIDATES,
    )
    validated_candidates = []
    for position, candidate in enumerate(replay_pool, start=1):
        method = (candidate.get("method_type") or "GET").upper()
        features = candidate.get("features") or {}
        if position > 1 and method != "GET" and not features.get("has_repeated_records"):
            logger.info(
                "⏭️ 부작용 가능성이 있는 비의미 POST 후보를 사전 검증에서 제외합니다: %s",
                candidate.get("api_url"),
            )
            continue

        logger.info(
            "🔎 후보 사전 보안·재현 검증 (%d/%d): %s",
            position,
            len(replay_pool),
            candidate.get("api_url"),
        )
        validation_status, validation_reason = await validate_candidate(candidate)
        candidate["validation_status"] = validation_status
        candidate["validation_reason"] = validation_reason
        logger.info(
            "🔎 [사전 검증] status=%s | %s",
            validation_status,
            validation_reason,
        )
        if validation_status == "passed":
            validated_candidates.append(candidate)

    if not validated_candidates:
        logger.warning("보안·재현·의미 gate를 통과한 후보가 없습니다.")
        failure_reason = "API 후보 사전 검증에 실패했습니다."
        _record_selection_failure(
            site_id,
            candidate_count=len(candidates),
            selection_decision="reject_or_observe_more",
            selection_reason=failure_reason,
            candidates=replay_pool,
            error_code="CANDIDATE_VALIDATION_FAILED",
        )
        notice_repo.update_site_crawl_state(
            site_id,
            crawl_status="failed",
            validation_status="valid",
            validation_error=failure_reason,
        )
        return None

    decision_pool = build_candidate_pool(
        validated_candidates,
        target_url,
        limit=LLM_TOP_K,
    )
    selection_decision, selection_reason = classify_candidate_decision(
        decision_pool
    )
    prioritized_candidates = await prioritize_candidates(
        validated_candidates,
        target_url=target_url,
    )
    if not prioritized_candidates:
        logger.warning("후보 선택에 실패했습니다.")
        _record_selection_failure(
            site_id,
            candidate_count=len(candidates),
            selection_decision=selection_decision,
            selection_reason=selection_reason,
            candidates=replay_pool,
            error_code="CANDIDATE_SELECTION_FAILED",
        )
        notice_repo.update_site_crawl_state(
            site_id,
            crawl_status="failed",
            validation_status="valid",
            validation_error=selection_reason,
        )
        return None

    selected_api = prioritized_candidates[0]
    logger.info("최종 선택된 API: %s", selected_api.get("api_url"))
    if selected_api.get("selection_reason"):
        logger.info("선택 근거: %s", selected_api.get("selection_reason"))
    if selected_api.get("selection_mode"):
        logger.info("선택 모드: %s", selected_api.get("selection_mode"))

    selected_api["site_id"] = site_id
    selected_api["_candidate_count"] = len(candidates)
    selected_api["_llm_used"] = selected_api.get("selection_mode") == "llm"
    selected_api["selection_decision"] = (
        selected_api.get("selection_decision") or selection_decision
    )
    selected_api["selection_reason"] = (
        selected_api.get("selection_reason") or selection_reason
    )
    selected_api["_candidate_evidence"] = build_candidate_evidence(
        replay_pool,
        selected_candidate_index=selected_api.get("api_index"),
    )
    selected_api["_pending_persistence"] = True
    notice_repo.update_site_crawl_state(
        site_id,
        crawl_status="pending",
        validation_status="valid",
        validation_error=None,
    )
    return selected_api
