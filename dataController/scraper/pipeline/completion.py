"""Atomic completion and fail-closed result materialization."""

from __future__ import annotations

import logging
from typing import Any, Dict

from repositories import notice_repo
from dataController.scraper.extraction.deterministic.models import ExtractionResult
from dataController.scraper.pipeline.constants import (
    MAX_EXTRACTION_EXPANSION_RATIO,
    MIN_EXTRACTION_COVERAGE_RATIO,
    MIN_RECORDS_FOR_COVERAGE_GATE,
    NOTICE_IDENTITY_VERSION,
)
from dataController.scraper.pipeline.processing_state import (
    classify_processing_result,
)
from dataController.scraper.pipeline.telemetry import agent_run_telemetry
from dataController.selector.detect_api_auto import save_api

logger = logging.getLogger(__name__)


def extraction_coverage_diagnostics(
    api: Dict[str, Any],
    result: ExtractionResult,
) -> Dict[str, Any]:
    """Describe page-wide count mismatches without rejecting extraction."""
    if result.status != "success":
        return {}

    validation_analysis = api.get("validation_analysis") or {}
    expected_count = int(
        validation_analysis.get("semantic_record_count") or 0
    )
    actual_count = len(result.notices)
    ratio = actual_count / expected_count if expected_count else 0.0
    reason_codes = []
    if (
        expected_count >= MIN_RECORDS_FOR_COVERAGE_GATE
        and ratio < MIN_EXTRACTION_COVERAGE_RATIO
    ):
        reason_codes.append("COVERAGE_MISMATCH")
    if (
        expected_count >= MIN_RECORDS_FOR_COVERAGE_GATE
        and ratio > MAX_EXTRACTION_EXPANSION_RATIO
    ):
        reason_codes.append("OVER_EXTRACTION")
    if not reason_codes:
        return {}
    return {
        "reason_codes": reason_codes,
        "semantic_record_count": expected_count,
        "extracted_record_count": actual_count,
        "extraction_ratio": ratio,
    }


def extraction_coverage_error(
    api: Dict[str, Any],
    result: ExtractionResult,
) -> None:
    """Compatibility shim: count mismatches are no longer fatal errors."""
    return None


def persist_api_after_extraction(api: Dict[str, Any], target_url: str) -> bool:
    if not api.get("_pending_persistence"):
        return True
    api_id = save_api(api, target_url)
    if not api_id:
        logger.error("공지 추출은 성공했지만 검증 API 저장에 실패했습니다.")
        return False
    api["_pending_persistence"] = False
    return True


def complete_notice_identity_upgrade(
    api: Dict[str, Any],
    api_url: str,
) -> None:
    """Record the identity version only after notice persistence succeeds."""
    config = api.get("extractor_config")
    if not config:
        return
    if int(config.get("notice_identity_version") or 0) >= NOTICE_IDENTITY_VERSION:
        return

    upgraded_config = dict(config)
    upgraded_config["notice_identity_version"] = NOTICE_IDENTITY_VERSION
    api["extractor_config"] = upgraded_config
    notice_repo.update_api_extractor(
        api_url,
        extractor_config=upgraded_config,
        schema_hash=api.get("schema_hash"),
        confidence=api.get("extractor_confidence"),
    )


def _prepare_notice_identity_config(api: Dict[str, Any]) -> None:
    """Upgrade the in-memory config before the atomic persistence boundary.

    Only ``notice_identity_version`` is safe to bump here unconditionally:
    it describes how notices are hashed for change-detection, not the
    extraction rule itself, so it can advance on any successful sync. The
    rule-content versions (``detail_url_base_version``,
    ``json_detail_template_version``, ``json_date_role_version``) must only
    advance when the rule was actually regenerated this run -
    ``build_active_rule_config`` already stamps those at approval time.
    Stamping them here too would mark a still-stale reused rule as current
    and permanently defeat ``active_rule_upgrade_required`` for it.
    """
    config = api.get("extractor_config")
    if not config:
        return
    if int(config.get("notice_identity_version") or 0) >= NOTICE_IDENTITY_VERSION:
        return
    upgraded_config = dict(config)
    upgraded_config["notice_identity_version"] = NOTICE_IDENTITY_VERSION
    api["extractor_config"] = upgraded_config


def complete_structured_processing(
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
    error_code = structured.get("error_code") or "NOTICE_EXTRACTION_FAILED"
    notices = structured.get("notices", []) if structured else []

    if processing_status in {"success", "valid_empty"}:
        _prepare_notice_identity_config(api)
        try:
            persisted = notice_repo.persist_verified_extraction(
                site_id=site_id,
                method_type=api.get("method_type") or "GET",
                api_url=api_url,
                headers=api.get("headers") or {},
                payload=api.get("payload") or {},
                source_hash=new_hash,
                notices=notices,
                processing_status=processing_status,
                extractor_config=api.get("extractor_config"),
                schema_hash=api.get("schema_hash"),
                extractor_confidence=api.get("extractor_confidence"),
                crawl_run_id=crawl_run_id,
            )
            api["api_id"] = persisted["api_id"]
            api["_pending_persistence"] = False
            structured["new_notice_count"] = persisted.get("new_notice_count", 0)
            structured["_notification_event_ids"] = persisted.get(
                "notification_event_ids", []
            )
        except Exception as exc:
            logger.error("검증 결과 원자적 저장 실패: %s", exc)
            processing_status = "failed"
            error_code = "DATABASE_ERROR"
            error = f"검증 결과 저장에 실패했습니다: {exc}"

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
            validation_error_code=error_code,
            validation_error=error,
        )
    telemetry = agent_run_telemetry(api)
    notice_repo.finish_crawl_run(
        crawl_run_id,
        status=processing_status,
        observed_hash=new_hash,
        processed_hash=new_hash if processing_status != "failed" else None,
        schema_hash=api.get("schema_hash"),
        extracted_notice_count=len(notices),
        error_code=error_code if processing_status == "failed" else None,
        error_message=error,
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
    return processing_status


def apply_deterministic_result(
    api: Dict[str, Any],
    api_url: str,
    result: ExtractionResult,
) -> Dict[str, Any]:
    coverage_diagnostics = extraction_coverage_diagnostics(api, result)
    if coverage_diagnostics:
        api["_coverage_diagnostics"] = coverage_diagnostics
        logger.warning(
            "⚠️ 후보/추출 건수 차이를 의미 진단으로 기록합니다: %s",
            coverage_diagnostics,
        )

    if result.extractor_config:
        api["extractor_config"] = result.extractor_config
        api["schema_hash"] = result.schema_hash
        api["extractor_confidence"] = result.confidence
        api["processing_status"] = result.status
    return result.as_processing_result(site_id=api.get("site_id"))


def failed_extraction_result(
    *,
    site_id: int,
    deterministic_error: str,
) -> Dict[str, Any]:
    return {
        "status": "error",
        "site_id": site_id,
        "notices": [],
        "error_code": "NOTICE_EXTRACTION_FAILED",
        "error_msg": (
            "결정론적 추출 규칙을 확정하지 못했습니다. "
            "검증되지 않은 결과는 저장하지 않습니다. "
            f"extractor_error={deterministic_error}"
        ),
    }

__all__ = [
    "apply_deterministic_result",
    "complete_notice_identity_upgrade",
    "complete_structured_processing",
    "extraction_coverage_diagnostics",
    "extraction_coverage_error",
    "failed_extraction_result",
    "persist_api_after_extraction",
]
