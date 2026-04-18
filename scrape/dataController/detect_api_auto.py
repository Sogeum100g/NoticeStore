import asyncio
import datetime
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytz

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from repositories import notice_repo
from scrape.dataController.candidate_collector import collect_candidates
from scrape.dataController.candidate_selector import select_candidate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

TEXTUAL_CONTENT_TYPE_HINTS = (
    "text/html", "application/json", "text/json", "application/xml", "text/xml",
    "text/plain", "application/javascript", "text/javascript", "application/graphql-response+json"
)


def save_site(url: str) -> Optional[int]:
    site_id = notice_repo.insert_site(
        site_url=url,
        created_at=datetime.datetime.now(pytz.timezone("Asia/Seoul")),
    )
    logger.info("신규 사이트 정보 DB 저장 완료 (ID: %s): %s", site_id, url)
    return site_id


def save_api(api: Dict[str, Any], url: str) -> None:
    site_id = notice_repo.select_site_id(url)
    notice_repo.insert_api(
        site_id=site_id,
        method_type=api.get("method_type"),
        api_url=api.get("api_url"),
        headers=api.get("headers"),
        payload=api.get("payload"),
        last_hash=None,
    )
    logger.info("신규 API 정보 DB 저장 완료")


def _build_validation_headers(candidate: Dict[str, Any]) -> Dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/json,application/xml;q=0.9,*/*;q=0.8",
    }

    request_headers = candidate.get("headers") or {}
    for key in ("Referer", "Origin", "X-Requested-With", "Accept-Language"):
        value = request_headers.get(key) or request_headers.get(key.lower())
        if value:
            headers[key] = value
    return headers


def _sync_validate_candidate(candidate: Dict[str, Any]) -> Tuple[str, str]:
    api_url = candidate.get("api_url")
    method = (candidate.get("method_type") or "GET").upper()
    source_kind = candidate.get("source_kind") or "unknown"
    payload_format = candidate.get("payload_format") or "query_only"
    body_payload = candidate.get("body_payload")

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

    request = Request(url=api_url, data=body_bytes, headers=headers, method=method)

    try:
        with urlopen(request, timeout=12) as response:
            raw = response.read(6000)
            content_type = response.headers.get("Content-Type", "").lower()
            text = raw.decode("utf-8", errors="ignore")

            is_textual = any(hint in content_type for hint in TEXTUAL_CONTENT_TYPE_HINTS)
            if response.status == 200 and is_textual and len(text.strip()) >= 80:
                return "passed", f"재현 검증 성공 ({method} {source_kind})"

            return "soft_failed", (
                f"응답은 받았지만 재현 신호가 약합니다. "
                f"status={response.status}, content-type={content_type}, body_len={len(text.strip())}"
            )

    except HTTPError as e:
        if source_kind == "document_html" and method == "GET":
            return "hard_failed", f"직접 문서 GET 재현 실패 (HTTP {e.code})"
        return "soft_failed", f"재현 검증 중 HTTPError 발생 (HTTP {e.code})"
    except URLError as e:
        if source_kind == "document_html" and method == "GET":
            return "hard_failed", f"직접 문서 GET 재현 실패 ({e})"
        return "soft_failed", f"재현 검증 중 URLError 발생 ({e})"
    except Exception as e:
        if source_kind == "document_html" and method == "GET":
            return "hard_failed", f"직접 문서 GET 재현 실패 ({e})"
        return "soft_failed", f"재현 검증 중 예외 발생 ({e})"


async def validate_candidate(candidate: Dict[str, Any]) -> Tuple[str, str]:
    return await asyncio.to_thread(_sync_validate_candidate, candidate)


async def find_api(target_url: str) -> Optional[Dict[str, Any]]:
    logger.info("🚀 [find_api 시작] 타겟 URL: %s", target_url)

    cached_api = notice_repo.select_api(target_url)
    if cached_api:
        logger.info("✅ [DB 조회] 저장된 API가 있어 캐시 결과를 반환합니다.")
        return cached_api

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
        return None

    selected_api = await select_candidate(candidates, target_url=target_url)
    if not selected_api:
        logger.warning("후보 선택에 실패했습니다.")
        return None

    logger.info("최종 선택된 API: %s", selected_api.get("api_url"))
    if selected_api.get("selection_reason"):
        logger.info("선택 근거: %s", selected_api.get("selection_reason"))

    validation_status, validation_reason = await validate_candidate(selected_api)
    logger.info("🔎 [재현 검증] status=%s | %s", validation_status, validation_reason)

    if validation_status == "hard_failed":
        logger.warning("❌ 재현 검증 hard fail 이므로 DB 저장을 중단합니다.")
        return None

    save_api(selected_api, target_url)
    selected_api["site_id"] = site_id
    selected_api["validation_status"] = validation_status
    selected_api["validation_reason"] = validation_reason
    return selected_api
