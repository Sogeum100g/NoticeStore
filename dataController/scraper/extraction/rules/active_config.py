"""Persistence adapter for evaluator-approved declarative extraction rules."""

from __future__ import annotations

import datetime
import hashlib
import json
from typing import TYPE_CHECKING, Any, Dict, Optional

from dataController.scraper.extraction.deterministic.models import ExtractionResult
from dataController.scraper.extraction.rules.contracts import ExtractorRuleV1
from dataController.scraper.extraction.rules.executor import execute_extractor_rule
from dataController.scraper.extraction.rules.hard_gate import validate_rule_execution
from dataController.scraper.navigation.url_normalizer import (
    canonicalize_notice_detail_url,
)
from dataController.scraper.sites.dcinside import (
    canonicalize_detail_url_for_target,
)

if TYPE_CHECKING:
    from dataController.scraper.agent.orchestrator import RuleActivationResult


ACTIVE_RULE_FORMAT = "agent_extractor_v1"
DETAIL_URL_BASE_VERSION = 4
JSON_DETAIL_TEMPLATE_VERSION = 1
JSON_DATE_ROLE_VERSION = 1


def is_active_rule_config(config: Any) -> bool:
    return bool(
        isinstance(config, dict)
        and config.get("format") == ACTIVE_RULE_FORMAT
        and config.get("activation", {}).get("status") == "active"
        and isinstance(config.get("rule"), dict)
    )


def load_active_rule(config: Any) -> Optional[ExtractorRuleV1]:
    """Validate persisted data again before each deterministic execution."""
    if not is_active_rule_config(config):
        return None
    try:
        return ExtractorRuleV1.model_validate(config["rule"])
    except (TypeError, ValueError):
        return None


def rule_schema_hash(rule: ExtractorRuleV1) -> str:
    canonical = json.dumps(
        rule.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_active_rule_config(
    activation: RuleActivationResult,
) -> Dict[str, Any]:
    """Build a storable envelope only for an explicitly approved result."""
    if (
        not activation.approved
        or activation.rule is None
        or activation.evaluation is None
        or activation.evaluation.decision != "pass"
    ):
        raise ValueError("승인되지 않은 규칙은 active config로 만들 수 없습니다.")

    return {
        "format": ACTIVE_RULE_FORMAT,
        "source_type": activation.rule.source_type,
        "rule": activation.rule.model_dump(mode="json"),
        "activation": {
            "status": "active",
            "rule_origin": activation.rule_origin,
            "evaluated_once": True,
            "evaluation": activation.evaluation.model_dump(mode="json"),
            "semantic_diagnostic_codes": (
                activation.hard_gate.semantic_diagnostic_codes
                if activation.hard_gate
                else []
            ),
            "usage_by_stage": activation.usage_by_stage,
        },
        "notice_identity_version": 2,
        "detail_url_base_version": DETAIL_URL_BASE_VERSION,
        "json_detail_template_version": JSON_DETAIL_TEMPLATE_VERSION,
        "json_date_role_version": JSON_DATE_ROLE_VERSION,
    }


def _materialize_notices(
    notices: list[dict[str, Optional[str]]],
    *,
    target_url: str,
) -> list[dict[str, Any]]:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    materialized = []
    for notice in notices:
        materialized.append(
            {
                **notice,
                "detail_url": canonicalize_detail_url_for_target(
                    canonicalize_notice_detail_url(notice.get("detail_url")),
                    target_url=target_url,
                    external_id=notice.get("external_id"),
                ),
                "url": target_url,
                "created_at": now,
                "scraped_at": now,
                "content_type": "notice",
            }
        )
    return materialized


def activation_as_extraction_result(
    activation: RuleActivationResult,
    *,
    target_url: str,
) -> ExtractionResult:
    if not activation.approved or activation.rule is None:
        return ExtractionResult(
            "failed",
            [],
            None,
            None,
            0.0,
            None,
            activation.reason or "규칙 활성화가 거부되었습니다.",
        )

    config = build_active_rule_config(activation)
    confidence = (
        activation.evaluation.confidence if activation.evaluation else 0.0
    )
    return ExtractionResult(
        "success",
        _materialize_notices(
            activation.approved_notices,
            target_url=target_url,
        ),
        config,
        rule_schema_hash(activation.rule),
        confidence,
        {
            "source_type": "approved_declarative_rule",
            "metrics": (
                activation.hard_gate.metrics.model_dump(mode="json")
                if activation.hard_gate
                else None
            ),
        },
    )


def execute_active_rule_config(
    raw_data: Any,
    *,
    config: Any,
    target_url: str,
    source_url: Optional[str] = None,
    semantic_record_count: int = 0,
) -> ExtractionResult:
    """Execute an active rule with hard gates and zero AI calls."""
    rule = load_active_rule(config)
    if rule is None:
        return ExtractionResult(
            "failed",
            [],
            config if isinstance(config, dict) else None,
            None,
            0.0,
            None,
            "active 추출 규칙이 없거나 저장 형식 검증에 실패했습니다.",
        )

    execution = execute_extractor_rule(
        raw_data,
        rule=rule,
        base_url=(
            source_url
            if rule.source_type == "html" and source_url
            else target_url
        ),
    )
    hard_gate = validate_rule_execution(
        execution,
        rule=rule,
        semantic_record_count=semantic_record_count,
    )
    if not hard_gate.passed:
        return ExtractionResult(
            "failed",
            [],
            config,
            rule_schema_hash(rule),
            0.0,
            {
                "source_type": "active_declarative_rule",
                "metrics": hard_gate.metrics.model_dump(mode="json"),
            },
            hard_gate.reason,
        )

    activation = config.get("activation") or {}
    approved_diagnostic_codes = sorted(
        activation.get("semantic_diagnostic_codes") or []
    )
    current_diagnostic_codes = sorted(hard_gate.semantic_diagnostic_codes)
    if current_diagnostic_codes != approved_diagnostic_codes:
        evaluation = activation.get("evaluation") or {}
        return ExtractionResult(
            "reevaluation_required",
            _materialize_notices(execution.notices, target_url=target_url),
            config,
            rule_schema_hash(rule),
            float(evaluation.get("confidence") or 0.0),
            {
                "source_type": "active_declarative_rule",
                "metrics": hard_gate.metrics.model_dump(mode="json"),
                "semantic_diagnostic_codes": current_diagnostic_codes,
                "approved_semantic_diagnostic_codes": (
                    approved_diagnostic_codes
                ),
            },
            (
                "후보/추출 건수 진단이 승인 당시와 달라 Result Evaluator "
                "재평가가 필요합니다."
            ),
        )

    evaluation = activation.get("evaluation") or {}
    return ExtractionResult(
        "success",
        _materialize_notices(execution.notices, target_url=target_url),
        config,
        rule_schema_hash(rule),
        float(evaluation.get("confidence") or 0.0),
        {
            "source_type": "active_declarative_rule",
            "metrics": hard_gate.metrics.model_dump(mode="json"),
            "semantic_diagnostic_codes": current_diagnostic_codes,
        },
    )
