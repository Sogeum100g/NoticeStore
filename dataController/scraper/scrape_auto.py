import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

import requests
from bs4 import BeautifulSoup

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from repositories import notice_repo
from dataController.security.url_safety import (
    ResponseTooLargeError,
    UnsafeUrlError,
    safe_request,
)
from dataController.scraper.processing_state import (
    classify_processing_result,
    decide_observation,
)
from dataController.scraper.deterministic_extractor import (
    ExtractionResult,
    extract_notices_deterministically,
)
from dataController.selector.detect_api_auto import find_api, save_api
from dataController.scraper.notice_sync import get_recent_info, process_notice_request, sync_notices_to_db
from dataController.scraper.page_extractors import (
    build_parser_text,
    expand_url,
    extract_next_data,
    extract_yt_data,
    get_text_hash,
    is_crawling_allowed,
    parse_youtube_community_data,
    remove_json_nulls,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _persist_api_after_extraction(api: Dict[str, Any], target_url: str) -> bool:
    if not api.get("_pending_persistence"):
        return True
    api_id = save_api(api, target_url)
    if not api_id:
        logger.error("공지 추출은 성공했지만 검증 API 저장에 실패했습니다.")
        return False
    api["_pending_persistence"] = False
    return True


def _complete_structured_processing(
    *,
    api: Dict[str, Any],
    target_url: str,
    site_id: int,
    api_url: str,
    new_hash: str,
    structured: Dict[str, Any],
    crawl_run_id: int,
) -> str:
    processing_status, error = classify_processing_result(structured)
    notices = structured.get("notices", []) if structured else []

    if processing_status in {"success", "valid_empty"}:
        if not _persist_api_after_extraction(api, target_url):
            processing_status = "failed"
            error = "검증 API 저장에 실패했습니다."
        elif processing_status == "success":
            sync_notices_to_db(site_id, notices, new_hash, api_url)
        else:
            notice_repo.update_api_processing_state(
                api_url,
                observed_hash=new_hash,
                processed_hash=new_hash,
                status="valid_empty",
            )

    if processing_status == "failed":
        if not api.get("_pending_persistence"):
            notice_repo.update_api_processing_state(
                api_url,
                observed_hash=new_hash,
                status="failed",
                error=error,
            )
        notice_repo.update_site_crawl_state(
            site_id,
            crawl_status="failed",
            validation_error=error,
        )
    else:
        notice_repo.update_site_crawl_state(
            site_id,
            crawl_status="active",
            validation_status="valid",
            validation_error=None,
        )

    notice_repo.finish_crawl_run(
        crawl_run_id,
        status=processing_status,
        observed_hash=new_hash,
        processed_hash=new_hash if processing_status != "failed" else None,
        schema_hash=api.get("schema_hash"),
        extracted_notice_count=len(notices),
        error_code="PROCESSING_FAILED" if processing_status == "failed" else None,
        error_message=error,
    )
    return processing_status


def _apply_deterministic_result(
    api: Dict[str, Any],
    api_url: str,
    result: ExtractionResult,
) -> Dict[str, Any]:
    if result.extractor_config:
        api["extractor_config"] = result.extractor_config
        api["schema_hash"] = result.schema_hash
        api["extractor_confidence"] = result.confidence
        api["processing_status"] = result.status
        if not api.get("_pending_persistence"):
            notice_repo.update_api_extractor(
                api_url,
                extractor_config=result.extractor_config,
                schema_hash=result.schema_hash,
                confidence=result.confidence,
            )
    return result.as_processing_result(site_id=api.get("site_id"))


def _failed_extraction_result(
    *,
    site_id: int,
    deterministic_error: str,
) -> Dict[str, Any]:
    return {
        "status": "error",
        "site_id": site_id,
        "notices": [],
        "error_msg": (
            "결정론적 추출 규칙을 확정하지 못했습니다. "
            "공지 추출에는 AI fallback을 사용하지 않습니다. "
            f"extractor_error={deterministic_error}"
        ),
    }


async def run_full_scrape(url: str) -> Dict[str, Any]:
    url = expand_url(url)
    response_template = {"status": "success", "site_id": None, "notices": []}

    def format_response(data: Dict[str, Any], status: str = "success") -> Dict[str, Any]:
        result = response_template.copy()
        result.update(data)
        result["status"] = status
        return result

    if not await is_crawling_allowed(url):
        blocked_site_id = notice_repo.select_site_id(url)
        if blocked_site_id:
            notice_repo.update_site_crawl_state(
                blocked_site_id,
                crawl_status="blocked",
                validation_status="valid",
                validation_error="robots.txt가 크롤링을 허용하지 않습니다.",
            )
        response_template["site_id"] = blocked_site_id
        return format_response({}, status="blocked")

    api = await find_api(url)
    if not api:
        logger.error("유효한 API 규격을 찾지 못했습니다: %s", url)
        return format_response({}, status="error")

    site_id = api.get("site_id")
    response_template["site_id"] = site_id

    api_url = api.get("api_url")
    method_type = api.get("method_type")
    headers = api.get("headers", {})
    payload = api.get("payload")
    processing_state = notice_repo.select_processing_state(api_url)
    crawl_run_id = notice_repo.create_crawl_run(
        site_id,
        api_id=api.get("api_id"),
        status="running",
        selection_mode=api.get("selection_mode") or "cached",
        processing_mode="extractor_pipeline",
        candidate_count=api.get("_candidate_count"),
        llm_used=bool(api.get("_llm_used")),
        llm_input_tokens=(api.get("_llm_usage") or {}).get("input_tokens"),
        llm_output_tokens=(api.get("_llm_usage") or {}).get("output_tokens"),
        llm_cost=(api.get("_llm_usage") or {}).get("cost"),
    )

    session = requests.Session()
    is_json_request = "application/json" in headers.get("content-type", "").lower()

    try:
        if method_type == "GET":
            response = safe_request(
                session,
                "GET",
                api_url,
                headers=headers,
                timeout=20,
            )
        else:
            response = safe_request(
                session,
                "POST",
                api_url,
                json=payload if is_json_request else None,
                data=None if is_json_request else payload,
                headers=headers,
                timeout=20,
            )
        response.encoding = response.apparent_encoding
        response.raise_for_status()
    except (requests.exceptions.RequestException, UnsafeUrlError, ResponseTooLargeError) as e:
        logger.error("❌ HTTP 요청 실패 (URL: %s): %s", api_url, e)
        notice_repo.finish_crawl_run(
            crawl_run_id,
            status="failed",
            error_code="HTTP_REQUEST_FAILED",
            error_message=str(e),
        )
        notice_repo.update_site_crawl_state(
            site_id,
            crawl_status="failed",
            validation_error=str(e),
        )
        return format_response({}, status="error")

    response_content_type = response.headers.get("Content-Type", "").lower()

    if "application/json" in response_content_type:
        logger.info("순수 JSON 응답 감지. 직접 데이터 처리를 진행합니다.")
        try:
            raw_data = response.json()
            cleaned_json = remove_json_nulls(raw_data)
            clean_text = json.dumps(cleaned_json, ensure_ascii=False, separators=(",", ":"))
            new_hash = get_text_hash(clean_text)

            observation_decision = decide_observation(new_hash, processing_state)
            if observation_decision == "process":
                logger.info("🔄 [변경 감지] 순수 JSON 데이터 동기화 시작")
                deterministic = extract_notices_deterministically(
                    cleaned_json,
                    content_type=response_content_type,
                    base_url=url,
                    extractor_config=api.get("extractor_config"),
                )
                if deterministic.status in {"success", "valid_empty"}:
                    logger.info(
                        "✅ 결정론적 JSON 추출 성공 (status=%s, count=%d)",
                        deterministic.status,
                        len(deterministic.notices),
                    )
                    structured = _apply_deterministic_result(
                        api,
                        api_url,
                        deterministic,
                    )
                else:
                    structured = _failed_extraction_result(
                        site_id=site_id,
                        deterministic_error=(
                            deterministic.error
                            or "JSON extractor rule unavailable"
                        ),
                    )
                processing_status = _complete_structured_processing(
                    api=api,
                    target_url=url,
                    site_id=site_id,
                    api_url=api_url,
                    new_hash=new_hash,
                    structured=structured or {},
                    crawl_run_id=crawl_run_id,
                )
                return format_response(
                    structured or {},
                    status=processing_status if processing_status != "success" else "success",
                )

            recent_info = get_recent_info(url) or {}
            notice_repo.finish_crawl_run(
                crawl_run_id,
                status=observation_decision,
                observed_hash=new_hash,
                processed_hash=(
                    new_hash if observation_decision == "unchanged" else None
                ),
                extracted_notice_count=0,
            )
            return format_response(recent_info, status=observation_decision)
        except json.JSONDecodeError:
            logger.warning("JSON 파싱 실패, HTML 파서(BS4)로 Fallback 진행합니다.")

    soup = BeautifulSoup(response.text, "lxml")

    next_data = extract_next_data(soup)
    if next_data:
        cleaned_json = remove_json_nulls(next_data)
        clean_text = json.dumps(cleaned_json, ensure_ascii=False, separators=(",", ":"))
        new_hash = get_text_hash(clean_text)

        observation_decision = decide_observation(new_hash, processing_state)
        if observation_decision == "process":
            logger.info("🔄 [변경 감지] Next.js 데이터 동기화 시작")
            deterministic = extract_notices_deterministically(
                cleaned_json,
                content_type="application/json",
                base_url=url,
                extractor_config=api.get("extractor_config"),
            )
            if deterministic.status in {"success", "valid_empty"}:
                structured = _apply_deterministic_result(
                    api,
                    api_url,
                    deterministic,
                )
            else:
                structured = _failed_extraction_result(
                    site_id=site_id,
                    deterministic_error=(
                        deterministic.error
                        or "Next.js extractor rule unavailable"
                    ),
                )
            processing_status = _complete_structured_processing(
                api=api,
                target_url=url,
                site_id=site_id,
                api_url=api_url,
                new_hash=new_hash,
                structured=structured or {},
                crawl_run_id=crawl_run_id,
            )
            soup.decompose()
            return format_response(structured or {}, status=processing_status)

        soup.decompose()
        recent_info = get_recent_info(url) or {}
        notice_repo.finish_crawl_run(
            crawl_run_id,
            status=observation_decision,
            observed_hash=new_hash,
            processed_hash=(
                new_hash if observation_decision == "unchanged" else None
            ),
            extracted_notice_count=0,
        )
        return format_response(recent_info, status=observation_decision)

    yt_data = extract_yt_data(soup)
    if yt_data:
        logger.info("🎯 유튜브 전용 데이터(ytInitialData) 감지. Python 구조적 파싱을 시작합니다.")
        extracted_notices = parse_youtube_community_data(yt_data, url)
        combined_text = "".join([n["title"] for n in extracted_notices])
        new_hash = get_text_hash(combined_text)
        soup.decompose()

        observation_decision = decide_observation(new_hash, processing_state)
        if observation_decision == "process":
            if extracted_notices:
                if not _persist_api_after_extraction(api, url):
                    return format_response({}, status="error")
                sync_notices_to_db(site_id, extracted_notices, new_hash, api_url)
                notice_repo.finish_crawl_run(
                    crawl_run_id,
                    status="success",
                    observed_hash=new_hash,
                    processed_hash=new_hash,
                    extracted_notice_count=len(extracted_notices),
                )
                notice_repo.update_site_crawl_state(
                    site_id,
                    crawl_status="active",
                    validation_status="valid",
                    validation_error=None,
                )
                logger.info("✅ 유튜브 데이터 파싱 및 동기화 성공 (Count: %d)", len(extracted_notices))
                return format_response({"notices": extracted_notices}, status="success")
            logger.warning("유튜브 데이터는 찾았으나, 파싱된 게시글이 없습니다.")
            notice_repo.update_api_processing_state(
                api_url,
                observed_hash=new_hash,
                processed_hash=new_hash,
                status="valid_empty",
            )
            notice_repo.finish_crawl_run(
                crawl_run_id,
                status="valid_empty",
                observed_hash=new_hash,
                processed_hash=new_hash,
                extracted_notice_count=0,
            )
            return format_response({"notices": []}, status="valid_empty")

        recent_info = get_recent_info(url) or {}
        notice_repo.finish_crawl_run(
            crawl_run_id,
            status=observation_decision,
            observed_hash=new_hash,
            processed_hash=(
                new_hash if observation_decision == "unchanged" else None
            ),
            extracted_notice_count=0,
        )
        return format_response(recent_info, status=observation_decision)

    soup.decompose()

    primary_text = build_parser_text(response.text, "lxml")
    new_hash = get_text_hash(primary_text)
    observation_decision = decide_observation(new_hash, processing_state)
    if observation_decision != "process":
        logger.info(
            "✅ 원문 처리 생략 (decision=%s). DB 기존 데이터 반환.",
            observation_decision,
        )
        recent_info = get_recent_info(url) or {}
        notice_repo.finish_crawl_run(
            crawl_run_id,
            status=observation_decision,
            observed_hash=new_hash,
            processed_hash=(
                new_hash if observation_decision == "unchanged" else None
            ),
            extracted_notice_count=0,
        )
        return format_response(recent_info, status=observation_decision)

    deterministic = extract_notices_deterministically(
        response.text,
        content_type=response_content_type or "text/html",
        base_url=url,
        extractor_config=api.get("extractor_config"),
    )
    if deterministic.status in {"success", "valid_empty"}:
        logger.info(
            "✅ 결정론적 HTML 추출 성공 (status=%s, count=%d)",
            deterministic.status,
            len(deterministic.notices),
        )
        deterministic_result = _apply_deterministic_result(
            api,
            api_url,
            deterministic,
        )
        processing_status = _complete_structured_processing(
            api=api,
            target_url=url,
            site_id=site_id,
            api_url=api_url,
            new_hash=new_hash,
            structured=deterministic_result,
            crawl_run_id=crawl_run_id,
        )
        return format_response(deterministic_result, status=processing_status)

    failed_result = _failed_extraction_result(
        site_id=site_id,
        deterministic_error=(
            deterministic.error or "HTML extractor rule unavailable"
        ),
    )
    processing_status = _complete_structured_processing(
        api=api,
        target_url=url,
        site_id=site_id,
        api_url=api_url,
        new_hash=new_hash,
        structured=failed_result,
        crawl_run_id=crawl_run_id,
    )
    logger.warning(
        "⚠️ 페이지 변경은 감지되었으나 결정론적 추출 규칙을 확정하지 못했습니다."
    )
    return format_response(failed_result, status=processing_status)
