import asyncio
import json
import logging
import os
from dataclasses import replace
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from repositories import notice_repo
from dataController.security.url_safety import (
    ResponseTooLargeError,
    UnsafeUrlError,
    safe_request,
)
from dataController.security.site_access import site_access_block_reason
from dataController.scraper.pipeline.processing_state import (
    decide_observation,
)
from dataController.scraper.pipeline.completion import (
    apply_deterministic_result as _apply_deterministic_result,
    complete_notice_identity_upgrade as _complete_notice_identity_upgrade,
    complete_structured_processing as _complete_structured_processing,
    extraction_coverage_diagnostics as _extraction_coverage_diagnostics,
    extraction_coverage_error as _extraction_coverage_error,
    failed_extraction_result as _failed_extraction_result,
    persist_api_after_extraction as _persist_api_after_extraction,
)
from dataController.scraper.pipeline.constants import NOTICE_IDENTITY_VERSION
from dataController.scraper.pipeline.telemetry import (
    agent_run_telemetry as _agent_run_telemetry,
)
from dataController.scraper.extraction.deterministic import (
    ExtractionResult,
    HTML_EXTRACTOR_CONFIG_VERSION,
    extract_notices_deterministically,
)
from dataController.scraper.extraction.rules.active_config import (
    DETAIL_URL_BASE_VERSION,
    JSON_DATE_ROLE_VERSION,
    JSON_DETAIL_TEMPLATE_VERSION,
    activation_as_extraction_result,
    execute_active_rule_config,
    is_active_rule_config,
    load_active_rule,
)
from dataController.scraper.sites.dcinside import gallery_list_id
from dataController.scraper.extraction.rules.executor import execute_extractor_rule
from dataController.scraper.extraction.rules.hard_gate import validate_rule_execution
from dataController.scraper.agent.orchestrator import (
    activate_candidate_rule,
)
from dataController.scraper.extraction.rules.adapter import (
    build_rule_based_candidate,
)
from dataController.selector.detect_api_auto import (
    find_api,
    save_api,
)
from dataController.scraper.persistence.notice_sync import (
    get_recent_info,
    process_notice_request,
    sync_notices_to_db,
)
from dataController.scraper.navigation.fetch_policy import (
    expand_url,
    is_crawling_allowed,
)
from dataController.scraper.sites.youtube import (
    extract_yt_data,
    parse_youtube_community_data,
)
from dataController.scraper.views.embedded_data import (
    extract_embedded_json_data,
    extract_javascript_hydration_data,
    extract_next_data,
)
from dataController.scraper.views.page_views import (
    build_html_source_views,
    get_text_hash,
    remove_json_nulls,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
EXTRACTION_AGENT_ENABLED_ENV = "EXTRACTION_AGENT_ENABLED"
EXTRACTION_AGENT_ROLLOUT_MODE_ENV = "EXTRACTION_AGENT_ROLLOUT_MODE"
EXTRACTION_AGENT_ROLLOUT_MODES = {"new_sites", "all"}


def _extraction_agent_enabled(api: Dict[str, Any]) -> bool:
    kill_switch_enabled = os.getenv(
        EXTRACTION_AGENT_ENABLED_ENV,
        "false",
    ).strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not kill_switch_enabled:
        return False

    rollout_mode = os.getenv(
        EXTRACTION_AGENT_ROLLOUT_MODE_ENV,
        "new_sites",
    ).strip().casefold()
    if rollout_mode not in EXTRACTION_AGENT_ROLLOUT_MODES:
        logger.error(
            "지원하지 않는 EXTRACTION_AGENT_ROLLOUT_MODE=%r. fail-closed 처리합니다.",
            rollout_mode,
        )
        return False
    if rollout_mode == "all":
        return True
    return bool(
        api.get("_pending_persistence")
        or is_active_rule_config(api.get("extractor_config"))
    )


def _semantic_record_count(api: Dict[str, Any]) -> int:
    analysis = api.get("validation_analysis") or {}
    try:
        return max(int(analysis.get("semantic_record_count") or 0), 0)
    except (TypeError, ValueError):
        return 0




async def _extract_with_agent_pipeline(
    raw_data: Any,
    *,
    content_type: str,
    target_url: str,
    source_url: str,
    api: Dict[str, Any],
) -> ExtractionResult:
    """Reuse approved rules, or activate one before any result is persisted."""
    stored_config = api.get("extractor_config")
    semantic_count = _semantic_record_count(api)
    active_rule_failed = False
    is_html_source = not (
        isinstance(raw_data, (dict, list)) or "json" in content_type
    )
    extraction_base_url = source_url if is_html_source else target_url

    active_rule_upgrade_required = bool(
        is_active_rule_config(stored_config)
        and (
            (
                stored_config.get("source_type") == "json"
                and (
                    int(stored_config.get("json_detail_template_version") or 0)
                    < JSON_DETAIL_TEMPLATE_VERSION
                    or int(stored_config.get("json_date_role_version") or 0)
                    < JSON_DATE_ROLE_VERSION
                )
            )
            or (
                stored_config.get("source_type") == "html"
                and int(stored_config.get("detail_url_base_version") or 0)
                < DETAIL_URL_BASE_VERSION
            )
        )
    )
    if is_active_rule_config(stored_config) and not active_rule_upgrade_required:
        active_result = execute_active_rule_config(
            raw_data,
            config=stored_config,
            target_url=target_url,
            source_url=source_url,
            semantic_record_count=semantic_count,
        )
        if active_result.status == "success":
            stored_activation = stored_config.get("activation") or {}
            stored_evaluation = stored_activation.get("evaluation") or {}
            api["_rule_activation"] = {
                "status": "reused",
                "reason": "기존 evaluator 승인 규칙을 재사용했습니다.",
                "evaluator_decision": stored_evaluation.get("decision"),
                "evaluator_confidence": stored_evaluation.get("confidence"),
            }
            logger.info(
                "✅ 승인된 active 규칙 재사용 성공 (AI 호출 0회, count=%d)",
                len(active_result.notices),
            )
            return active_result
        active_rule_failed = True
        if active_result.status == "reevaluation_required":
            if not _extraction_agent_enabled(api):
                api["_rule_activation"] = {
                    "status": "reused_pending_reevaluation",
                    "reason": active_result.error,
                }
                logger.warning(
                    "⚠️ Result Evaluator가 비활성화되어 기존 승인 규칙을 "
                    "유지하고 의미 재평가를 보류합니다: %s",
                    active_result.error,
                )
                return replace(
                    active_result,
                    status="success",
                    error=None,
                )
            logger.warning(
                "⚠️ active 규칙의 의미 진단이 변경되었습니다. "
                "Result Evaluator 재평가가 필요합니다: %s",
                active_result.error,
            )
        else:
            logger.warning(
                "⚠️ active 규칙 검증 실패. 규칙 재활성화가 필요합니다: %s",
                active_result.error,
            )
        if not _extraction_agent_enabled(api):
            api["_rule_activation"] = {
                "status": "failed",
                "reason": active_result.error,
            }
            return active_result
    elif active_rule_upgrade_required:
        active_rule_failed = True
        if stored_config.get("source_type") == "json":
            logger.info(
                "🔄 JSON 추출 의미 규칙 업그레이드 감지 "
                "(url_template=%s, date_role=%s). active 규칙을 "
                "재활성화합니다.",
                stored_config.get("json_detail_template_version") or 0,
                stored_config.get("json_date_role_version") or 0,
            )
        else:
            logger.info(
                "🔄 HTML 상세 이동 해석기 업그레이드 감지 "
                "(detail_url_base=%s). active 규칙을 재활성화합니다.",
                stored_config.get("detail_url_base_version") or 0,
            )

    legacy_config = None if active_rule_failed else stored_config
    deterministic = extract_notices_deterministically(
        raw_data,
        content_type=content_type,
        base_url=extraction_base_url,
        extractor_config=legacy_config,
    )

    # The feature flag makes rollout reversible. Once an active envelope exists,
    # it is always reused above even if the flag is later disabled.
    if not _extraction_agent_enabled(api):
        return deterministic

    rule_based_candidate = build_rule_based_candidate(raw_data, deterministic)
    template_site_id = None
    if is_html_source and gallery_list_id(source_url):
        templates = []
        # A version upgrade must re-evaluate the saved rule before discarding it.
        if is_active_rule_config(stored_config):
            templates.append({"site_id": api.get("site_id"), "extractor_config": stored_config})
        templates.extend(await asyncio.to_thread(
            notice_repo.select_dcinside_rule_templates,
            api.get("site_id"),
        ))
        for template in templates:
            template_rule = load_active_rule(template.get("extractor_config"))
            if template_rule is None or template_rule.source_type != "html":
                continue
            execution = execute_extractor_rule(raw_data, rule=template_rule, base_url=source_url)
            gate = validate_rule_execution(
                execution,
                rule=template_rule,
                semantic_record_count=semantic_count,
                baseline_notices=deterministic.notices,
            )
            if gate.passed:
                rule_based_candidate = template_rule
                template_site_id = template["site_id"]
                break
    detected_source_type = (
        (deterministic.extractor_config or {}).get("source_type")
        or (
            "json"
            if isinstance(raw_data, (dict, list)) or "json" in content_type
            else "html"
        )
    )
    activation = await activate_candidate_rule(
        raw_data,
        source_type=detected_source_type,
        target_url=target_url,
        source_url=source_url,
        semantic_record_count=semantic_count,
        baseline_notices=deterministic.notices,
        rule_based_candidate=rule_based_candidate,
    )
    if template_site_id is not None and activation.rule_origin == "rule_based":
        activation = replace(
            activation,
            rule_origin="site_template",
            diagnostics={**activation.diagnostics, "template_site_id": template_site_id},
        )
    api["_extraction_agent_usage"] = [
        *activation.usage_by_stage,
        {
            "stage": "rule_activation",
            "provider": "local",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": 0.0,
            "status": activation.status,
            "failure_code": activation.failure_code,
            "diagnostics": activation.diagnostics,
        },
    ]
    api["_rule_activation"] = {
        "status": activation.status,
        "reason": activation.reason,
        "failure_code": activation.failure_code,
        "diagnostics": activation.diagnostics,
        "evaluator_decision": (
            activation.evaluation.decision if activation.evaluation else None
        ),
        "evaluator_confidence": (
            activation.evaluation.confidence if activation.evaluation else None
        ),
    }
    if not activation.approved:
        return ExtractionResult(
            "failed",
            [],
            stored_config if active_rule_failed else None,
            None,
            0.0,
            None,
            activation.reason or "새 추출 규칙 활성화가 거부되었습니다.",
        )
    logger.info(
        "✅ 새 규칙 활성화 승인 (origin=%s, count=%d)",
        activation.rule_origin,
        len(activation.approved_notices),
    )
    return activation_as_extraction_result(
        activation,
        target_url=target_url,
    )


def _refresh_notice_identity_decision(
    decision: str,
    api: Dict[str, Any],
) -> str:
    """Reconcile cached source once after the notice identity rules change."""
    config = api.get("extractor_config") or {}
    stored_version = int(config.get("notice_identity_version") or 0)
    if decision == "unchanged" and stored_version < NOTICE_IDENTITY_VERSION:
        logger.info(
            "🔄 공지 식별 규칙 업그레이드 감지 (v%s -> v%s). "
            "동일 원문을 다시 동기화합니다.",
            stored_version,
            NOTICE_IDENTITY_VERSION,
        )
        return "process"
    return decision


def _refresh_html_extractor_decision(
    decision: str,
    api: Dict[str, Any],
) -> str:
    config = api.get("extractor_config") or {}
    if (
        decision == "unchanged"
        and not is_active_rule_config(config)
        and config.get("source_type") == "html"
        and int(config.get("version") or 0) < HTML_EXTRACTOR_CONFIG_VERSION
    ):
        logger.info(
            "🔄 HTML 추출기 규칙 업그레이드 감지 (v%s -> v%s). "
            "동일 원문을 한 번 재처리합니다.",
            config.get("version") or 0,
            HTML_EXTRACTOR_CONFIG_VERSION,
        )
        return "process"
    return decision


def _refresh_detail_url_base_decision(
    decision: str,
    api: Dict[str, Any],
) -> str:
    """Rebuild HTML detail URLs after a URL/navigation resolver upgrade."""
    config = api.get("extractor_config") or {}
    if (
        decision == "unchanged"
        and config.get("source_type") == "html"
        and int(config.get("detail_url_base_version") or 0)
        < DETAIL_URL_BASE_VERSION
    ):
        logger.info(
            "🔄 HTML 상세 이동 해석기 업그레이드 감지 (v%s -> v%s). "
            "동일 원문을 한 번 재처리합니다.",
            config.get("detail_url_base_version") or 0,
            DETAIL_URL_BASE_VERSION,
        )
        return "process"
    return decision


def _refresh_json_detail_template_decision(
    decision: str,
    api: Dict[str, Any],
) -> str:
    """Re-evaluate cached JSON after derived detail URL rule upgrades."""
    config = api.get("extractor_config") or {}
    if (
        decision == "unchanged"
        and config.get("source_type") == "json"
        and (
            (
                is_active_rule_config(config)
                and (
                    int(config.get("json_detail_template_version") or 0)
                    < JSON_DETAIL_TEMPLATE_VERSION
                    or int(config.get("json_date_role_version") or 0)
                    < JSON_DATE_ROLE_VERSION
                )
            )
            or (
                not is_active_rule_config(config)
                and int(config.get("version") or 0) < 2
            )
        )
    ):
        logger.info(
            "🔄 JSON 추출 의미 규칙 업그레이드 감지 "
            "(url_template=%s, date_role=%s). "
            "동일 원문을 한 번 재처리합니다.",
            config.get("json_detail_template_version") or 0,
            config.get("json_date_role_version") or 0,
        )
        return "process"
    return decision


def _update_site_after_skipped_observation(
    *,
    site_id: int,
    observation_decision: str,
    processing_state: Dict[str, Any],
) -> None:
    """Keep site health consistent when extraction is intentionally skipped."""
    if observation_decision == "unchanged":
        notice_repo.activate_site_after_successful_sync(site_id)
        return

    if observation_decision not in {"backoff", "retry_exhausted"}:
        return

    previous_error = str(processing_state.get("last_error") or "").strip()
    if observation_decision == "retry_exhausted":
        fallback_error = "공지 추출 재시도 횟수를 모두 소진했습니다."
    else:
        fallback_error = "이전 공지 추출 실패로 다음 재시도 시각까지 대기합니다."

    notice_repo.update_site_crawl_state(
        site_id,
        crawl_status="failed",
        validation_status="valid",
        validation_error_code="NOTICE_EXTRACTION_FAILED",
        validation_error=previous_error or fallback_error,
    )


async def run_full_scrape(
    url: str,
    *,
    site_id: int | None = None,
    _candidate_queue: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if _candidate_queue:
        api = dict(_candidate_queue[0])
        fallback_candidates = list(_candidate_queue[1:])
    else:
        url = expand_url(url)
        api = await find_api(url, site_id=site_id)
        fallback_candidates = (
            list(api.pop("_fallback_candidates", [])) if api else []
        )
    response_template = {
        "status": "success",
        "site_id": site_id,
        "notices": [],
    }

    def format_response(data: Dict[str, Any], status: str = "success") -> Dict[str, Any]:
        result = response_template.copy()
        result.update(data)
        result["status"] = status
        return result

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
    candidate_evidence = [
        {
            **item,
            "selected": item.get("api_index") == api.get("api_index"),
        }
        for item in (api.get("_candidate_evidence") or [])
    ]
    crawl_run_id = notice_repo.create_crawl_run(
        site_id,
        api_id=api.get("api_id"),
        status="running",
        selection_mode=api.get("selection_mode") or "cached",
        processing_mode="extractor_pipeline",
        candidate_count=api.get("_candidate_count"),
        selection_decision=(
            api.get("selection_decision")
            or ("cached_reuse" if not api.get("_pending_persistence") else None)
        ),
        selection_reason=api.get("selection_reason"),
        selected_candidate_index=api.get("api_index"),
        candidate_evidence=candidate_evidence or None,
        llm_used=bool(api.get("_llm_used")),
        llm_input_tokens=(api.get("_llm_usage") or {}).get("input_tokens"),
        llm_output_tokens=(api.get("_llm_usage") or {}).get("output_tokens"),
        llm_cost=(api.get("_llm_usage") or {}).get("cost"),
    )

    async def retry_next_candidate(
        *,
        error_code: str,
        error_message: str,
    ) -> Optional[Dict[str, Any]]:
        if not fallback_candidates:
            return None
        telemetry = _agent_run_telemetry(api)
        notice_repo.finish_crawl_run(
            crawl_run_id,
            status="failed",
            error_code=error_code,
            error_message=error_message,
            llm_used=telemetry["llm_used"],
            llm_input_tokens=telemetry["input_tokens"],
            llm_output_tokens=telemetry["output_tokens"],
            llm_cost=telemetry["cost"],
            agent_stage_telemetry=telemetry["stages"] or None,
            rule_activation_status=telemetry["activation_status"],
            rule_activation_reason=telemetry["activation_reason"],
            evaluator_decision=telemetry["evaluator_decision"],
            evaluator_confidence=telemetry["evaluator_confidence"],
        )
        logger.warning(
            "↪️ 후보 추출 실패로 다음 API를 재시도합니다 "
            "(failed_index=%s, next_index=%s, remaining=%d)",
            api.get("api_index"),
            fallback_candidates[0].get("api_index"),
            len(fallback_candidates),
        )
        return await run_full_scrape(
            url,
            site_id=site_id,
            _candidate_queue=fallback_candidates,
        )

    def finish_site_access_blocked(reason: str) -> Dict[str, Any]:
        notice_repo.finish_crawl_run(
            crawl_run_id,
            status="blocked",
            error_code="SITE_ACCESS_BLOCKED",
            error_message=reason,
        )
        notice_repo.update_site_crawl_state(
            site_id,
            crawl_status="blocked",
            validation_status="valid",
            validation_error_code="SITE_ACCESS_BLOCKED",
            validation_error=reason,
        )
        return format_response({}, status="blocked")

    session = requests.Session()
    is_json_request = "application/json" in headers.get("content-type", "").lower()
    snapshot = api.pop("_validated_response_snapshot", None)
    if snapshot:
        response_status = snapshot.get("status_code")
        response_text = str(snapshot.get("body_text") or "")
        response_content_type = str(snapshot.get("content_type") or "").lower()
        response_source_url = str(snapshot.get("response_url") or api_url)
        logger.info(
            "📦 검증 단계 원문 스냅샷 재사용 "
            "(decoded_bytes=%s, source=%s)",
            snapshot.get("decoded_bytes"),
            response_source_url,
        )
    else:
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
            response_status = response.status_code
            response.encoding = response.apparent_encoding
            response.raise_for_status()
            response_text = response.text
            response_content_type = response.headers.get(
                "Content-Type", ""
            ).lower()
            response_source_url = response.url or api_url
            response_metrics = getattr(response, "__dict__", {}).get(
                "_response_size_metrics"
            )
            if response_metrics is not None:
                logger.info(
                    "📦 [응답 크기] transfer_bytes=%d decoded_bytes=%d "
                    "content_type=%s content_encoding=%s",
                    response_metrics.transfer_bytes,
                    response_metrics.decoded_bytes,
                    response_metrics.content_type,
                    response_metrics.content_encoding,
                )
        except (
            requests.exceptions.RequestException,
            UnsafeUrlError,
            ResponseTooLargeError,
        ) as e:
            logger.error("❌ HTTP 요청 실패 (URL: %s): %s", api_url, e)
            error_response = getattr(e, "response", None)
            access_block_reason = site_access_block_reason(
                status_code=getattr(error_response, "status_code", None),
                url=getattr(error_response, "url", None) or api_url,
            )
            if access_block_reason:
                fallback_result = await retry_next_candidate(
                    error_code="CANDIDATE_SITE_ACCESS_BLOCKED",
                    error_message=access_block_reason,
                )
                if fallback_result is not None:
                    return fallback_result
                return finish_site_access_blocked(access_block_reason)
            fallback_result = await retry_next_candidate(
                error_code="CANDIDATE_HTTP_REQUEST_FAILED",
                error_message=str(e),
            )
            if fallback_result is not None:
                return fallback_result
            notice_repo.finish_crawl_run(
                crawl_run_id,
                status="failed",
                error_code="HTTP_REQUEST_FAILED",
                error_message=str(e),
            )
            notice_repo.update_site_crawl_state(
                site_id,
                crawl_status="failed",
                validation_error_code="SITE_UNREACHABLE",
                validation_error=str(e),
            )
            return format_response({}, status="error")

    access_block_reason = site_access_block_reason(
        status_code=response_status,
        url=response_source_url,
        body_text=response_text,
    )
    if access_block_reason:
        logger.warning("🚫 사이트 접근 차단 응답 감지: %s", access_block_reason)
        fallback_result = await retry_next_candidate(
            error_code="CANDIDATE_SITE_ACCESS_BLOCKED",
            error_message=access_block_reason,
        )
        if fallback_result is not None:
            return fallback_result
        return finish_site_access_blocked(access_block_reason)

    if "application/json" in response_content_type:
        logger.info("순수 JSON 응답 감지. 직접 데이터 처리를 진행합니다.")
        try:
            raw_data = json.loads(response_text)
            cleaned_json = remove_json_nulls(raw_data)
            clean_text = json.dumps(cleaned_json, ensure_ascii=False, separators=(",", ":"))
            new_hash = get_text_hash(clean_text)

            observation_decision = decide_observation(new_hash, processing_state)
            observation_decision = _refresh_notice_identity_decision(
                observation_decision,
                api,
            )
            observation_decision = _refresh_json_detail_template_decision(
                observation_decision,
                api,
            )
            if observation_decision == "process":
                logger.info("🔄 [변경 감지] 순수 JSON 데이터 동기화 시작")
                deterministic = await _extract_with_agent_pipeline(
                    cleaned_json,
                    content_type=response_content_type,
                    target_url=url,
                    source_url=response_source_url,
                    api=api,
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
                if (structured or {}).get("status") == "error":
                    fallback_result = await retry_next_candidate(
                        error_code="CANDIDATE_EXTRACTION_FAILED",
                        error_message=(
                            structured.get("error_msg")
                            or "JSON 후보 추출이 거부됐습니다."
                        ),
                    )
                    if fallback_result is not None:
                        return fallback_result
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
            _update_site_after_skipped_observation(
                site_id=site_id,
                observation_decision=observation_decision,
                processing_state=processing_state,
            )
            return format_response(recent_info, status=observation_decision)
        except json.JSONDecodeError:
            logger.warning("JSON 파싱 실패, HTML 파서(BS4)로 Fallback 진행합니다.")

    soup = BeautifulSoup(response_text, "lxml")

    next_data = extract_next_data(soup)
    application_json = extract_embedded_json_data(soup) if not next_data else None
    javascript_json = (
        extract_javascript_hydration_data(soup)
        if not next_data and not application_json
        else None
    )
    embedded_json = next_data or application_json or javascript_json
    if embedded_json:
        embedded_source_label = (
            "Next.js"
            if next_data
            else "embedded JSON"
            if application_json
            else "JavaScript hydration"
        )
        cleaned_json = remove_json_nulls(embedded_json)
        clean_text = json.dumps(cleaned_json, ensure_ascii=False, separators=(",", ":"))
        new_hash = get_text_hash(clean_text)

        observation_decision = decide_observation(new_hash, processing_state)
        observation_decision = _refresh_notice_identity_decision(
            observation_decision,
            api,
        )
        observation_decision = _refresh_json_detail_template_decision(
            observation_decision,
            api,
        )
        if observation_decision == "process":
            logger.info(
                "🔄 [변경 감지] %s 데이터 동기화 시작",
                embedded_source_label,
            )
            deterministic = await _extract_with_agent_pipeline(
                cleaned_json,
                content_type="application/json",
                target_url=url,
                source_url=response_source_url,
                api=api,
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
                        or f"{embedded_source_label} extractor rule unavailable"
                    ),
                )
            if (structured or {}).get("status") == "error":
                fallback_result = await retry_next_candidate(
                    error_code="CANDIDATE_EXTRACTION_FAILED",
                    error_message=(
                        structured.get("error_msg")
                        or f"{embedded_source_label} 후보 추출이 거부됐습니다."
                    ),
                )
                if fallback_result is not None:
                    soup.decompose()
                    return fallback_result
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
        _update_site_after_skipped_observation(
            site_id=site_id,
            observation_decision=observation_decision,
            processing_state=processing_state,
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
                    notice_repo.update_site_crawl_state(
                        site_id,
                        crawl_status="failed",
                        validation_error_code="DATABASE_ERROR",
                        validation_error="검증 API 저장에 실패했습니다.",
                    )
                    return format_response({}, status="error")
                persisted = sync_notices_to_db(
                    site_id,
                    extracted_notices,
                    new_hash,
                    api_url,
                    crawl_run_id=crawl_run_id,
                )
                notice_repo.finish_crawl_run(
                    crawl_run_id,
                    status="success",
                    observed_hash=new_hash,
                    processed_hash=new_hash,
                    extracted_notice_count=len(extracted_notices),
                )
                notice_repo.activate_site_after_successful_sync(site_id)
                logger.info("✅ 유튜브 데이터 파싱 및 동기화 성공 (Count: %d)", len(extracted_notices))
                return format_response(
                    {
                        "notices": extracted_notices,
                        "new_notice_count": persisted["new_notice_count"],
                        "_notification_event_ids": persisted[
                            "notification_event_ids"
                        ],
                    },
                    status="success",
                )
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
            notice_repo.activate_site_after_successful_sync(site_id)
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
        _update_site_after_skipped_observation(
            site_id=site_id,
            observation_decision=observation_decision,
            processing_state=processing_state,
        )
        return format_response(recent_info, status=observation_decision)

    soup.decompose()

    source_views = build_html_source_views(response_text, "lxml")
    api["_source_view_metrics"] = source_views.metrics()
    new_hash = source_views.analysis_hash
    observation_decision = decide_observation(new_hash, processing_state)
    observation_decision = _refresh_notice_identity_decision(
        observation_decision,
        api,
    )
    observation_decision = _refresh_html_extractor_decision(
        observation_decision,
        api,
    )
    observation_decision = _refresh_detail_url_base_decision(
        observation_decision,
        api,
    )
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
        _update_site_after_skipped_observation(
            site_id=site_id,
            observation_decision=observation_decision,
            processing_state=processing_state,
        )
        return format_response(recent_info, status=observation_decision)

    deterministic = await _extract_with_agent_pipeline(
        source_views.raw_html,
        content_type=response_content_type or "text/html",
        target_url=url,
        source_url=response_source_url,
        api=api,
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
    fallback_result = await retry_next_candidate(
        error_code="CANDIDATE_EXTRACTION_FAILED",
        error_message=failed_result["error_msg"],
    )
    if fallback_result is not None:
        return fallback_result
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
