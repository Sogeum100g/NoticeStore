"""Deterministic invariants and semantic diagnostics for rule evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from dataController.scraper.extraction.rules.executor import (
    RuleExecutionEvidence,
    RuleExecutionResult,
)
from dataController.scraper.extraction.contracts import (
    EvaluatedNoticeEvidenceV2,
    ResultEvaluationRequestV2,
    RuleValidationMetrics,
    SourceFieldValuesV1,
    SourceRecordEvidenceV1,
)
from dataController.scraper.extraction.rules.contracts import ExtractorRuleV1
from dataController.scraper.navigation.url_normalizer import (
    canonicalize_notice_detail_url,
)


@dataclass(frozen=True)
class HardGatePolicy:
    min_extracted_records: int = 1
    min_records_for_coverage_gate: int = 4
    min_coverage_ratio: float = 0.5
    max_extraction_ratio: float = 1.2
    max_missing_title_ratio: float = 0.25
    max_invalid_detail_url_ratio: float = 0.2
    max_invalid_date_ratio: float = 0.5
    max_duplicate_ratio: float = 0.2
    min_baseline_field_count: int = 2
    min_baseline_field_coverage: float = 0.5
    max_field_coverage_drop: float = 0.2


@dataclass(frozen=True)
class HardGateResult:
    passed: bool
    metrics: RuleValidationMetrics
    reason_codes: List[str]
    semantic_diagnostic_codes: List[str]
    reason: str


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _invalid_detail_url_count(execution: RuleExecutionResult) -> int:
    invalid = 0
    for notice in execution.notices:
        value = notice.get("detail_url")
        parsed = urlsplit(value or "")
        if (
            not value
            or parsed.scheme.casefold() not in {"http", "https"}
            or not parsed.netloc
        ):
            invalid += 1
    return invalid


def _duplicate_record_count(execution: RuleExecutionResult) -> int:
    seen = set()
    duplicate_count = 0
    for notice in execution.notices:
        identity: Tuple[object, ...]
        if notice.get("external_id"):
            identity = ("external_id", notice["external_id"])
        elif notice.get("detail_url"):
            identity = (
                "detail_url",
                canonicalize_notice_detail_url(notice["detail_url"]),
            )
        else:
            identity = (
                "content",
                (notice.get("title") or "").casefold(),
                notice.get("published_at"),
            )
        if identity in seen:
            duplicate_count += 1
        else:
            seen.add(identity)
    return duplicate_count


def _field_coverage(
    notices: List[Dict[str, Optional[str]]],
    field_name: str,
) -> float:
    return _ratio(
        sum(bool(notice.get(field_name)) for notice in notices),
        len(notices),
    )


def validate_rule_execution(
    execution: RuleExecutionResult,
    *,
    rule: ExtractorRuleV1,
    semantic_record_count: int = 0,
    baseline_notices: Optional[List[Dict[str, Optional[str]]]] = None,
    policy: Optional[HardGatePolicy] = None,
) -> HardGateResult:
    policy = policy or HardGatePolicy()
    extracted_count = len(execution.notices)
    baseline_record_count = len(baseline_notices or [])
    semantic_record_count = max(semantic_record_count, 0)
    # The candidate analyzer scans the whole document and can count unrelated
    # event/banner lists.  Keep that page-wide count visible to the semantic
    # evaluator while using the same-source baseline (when available) for the
    # scoped coverage metric.
    expected_record_count = baseline_record_count or semantic_record_count
    reference_count = max(expected_record_count, execution.source_record_count)
    coverage_ratio = min(1.0, _ratio(extracted_count, reference_count))
    extraction_ratio = _ratio(extracted_count, semantic_record_count)

    detail_rule_configured = rule.fields.detail_url is not None
    date_rule_configured = rule.fields.published_at is not None
    invalid_detail_url_count = (
        _invalid_detail_url_count(execution) if detail_rule_configured else 0
    )
    invalid_date_count = (
        sum(not notice.get("published_at") for notice in execution.notices)
        if date_rule_configured
        else 0
    )
    duplicate_count = _duplicate_record_count(execution)
    metrics = RuleValidationMetrics(
        semantic_record_count=semantic_record_count,
        extracted_record_count=extracted_count,
        coverage_ratio=coverage_ratio,
        missing_title_count=execution.rejected_record_count,
        invalid_detail_url_count=invalid_detail_url_count,
        invalid_date_count=invalid_date_count,
        duplicate_record_count=duplicate_count,
        source_record_count=max(execution.source_record_count, 0),
        baseline_record_count=baseline_record_count,
        reference_record_count=max(reference_count, 0),
        extraction_ratio=extraction_ratio,
    )

    reasons: List[str] = []
    semantic_diagnostics: List[str] = []
    if execution.status == "failed":
        reasons.append("EXECUTION_FAILED")
    if extracted_count < policy.min_extracted_records:
        reasons.append("NO_EXTRACTED_RECORDS")
    if (
        semantic_record_count >= policy.min_records_for_coverage_gate
        and extraction_ratio < policy.min_coverage_ratio
    ):
        semantic_diagnostics.append("COVERAGE_MISMATCH")
    if (
        semantic_record_count >= policy.min_records_for_coverage_gate
        and extraction_ratio > policy.max_extraction_ratio
    ):
        semantic_diagnostics.append("OVER_EXTRACTION")
    if (
        execution.source_record_count > 0
        and _ratio(execution.rejected_record_count, execution.source_record_count)
        > policy.max_missing_title_ratio
    ):
        reasons.append("MISSING_TITLES")
    if (
        detail_rule_configured
        and extracted_count > 0
        and _ratio(invalid_detail_url_count, extracted_count)
        > policy.max_invalid_detail_url_ratio
    ):
        reasons.append("INVALID_DETAIL_URLS")
    if (
        date_rule_configured
        and extracted_count > 0
        and _ratio(invalid_date_count, extracted_count)
        > policy.max_invalid_date_ratio
    ):
        reasons.append("INVALID_DATES")
    if (
        extracted_count > 0
        and _ratio(duplicate_count, extracted_count) > policy.max_duplicate_ratio
    ):
        reasons.append("DUPLICATE_RECORDS")
    for field_name in ("author", "published_at", "detail_url", "external_id"):
        baseline_values = sum(
            bool(notice.get(field_name)) for notice in (baseline_notices or [])
        )
        baseline_coverage = _field_coverage(
            baseline_notices or [],
            field_name,
        )
        candidate_coverage = _field_coverage(execution.notices, field_name)
        if (
            baseline_values >= policy.min_baseline_field_count
            and baseline_coverage >= policy.min_baseline_field_coverage
            and baseline_coverage - candidate_coverage
            > policy.max_field_coverage_drop
        ):
            reasons.append(
                f"FIELD_COVERAGE_REGRESSION_{field_name.upper()}"
            )

    return HardGateResult(
        passed=not reasons,
        metrics=metrics,
        reason_codes=reasons,
        semantic_diagnostic_codes=semantic_diagnostics,
        reason=(
            (
                "결정론적 hard gate를 통과했으며 의미 평가가 필요한 "
                "건수 차이가 있습니다: " + ", ".join(semantic_diagnostics)
            )
            if not reasons and semantic_diagnostics
            else "결정론적 hard gate를 통과했습니다."
            if not reasons
            else "결정론적 hard gate 실패: " + ", ".join(reasons)
        ),
    )


def build_result_evaluation_request(
    *,
    target_url: str,
    source_url: str,
    rule: ExtractorRuleV1,
    execution: RuleExecutionResult,
    hard_gate: HardGateResult,
) -> ResultEvaluationRequestV2:
    if not hard_gate.passed:
        raise ValueError("hard gate를 통과한 결과만 의미 평가할 수 있습니다.")

    samples = []
    for index in _representative_sample_indices(execution.notices):
        notice = execution.notices[index]
        evidence = execution.evidence[index]
        samples.append(
            EvaluatedNoticeEvidenceV2(
                title=notice.get("title") or "",
                author=notice.get("author"),
                published_at=notice.get("published_at"),
                detail_url=notice.get("detail_url"),
                external_id=notice.get("external_id"),
                source=_source_record_evidence(evidence),
            )
        )

    return ResultEvaluationRequestV2(
        version=2,
        target_url=target_url,
        source_url=source_url,
        rule=rule,
        metrics=hard_gate.metrics,
        semantic_diagnostic_codes=hard_gate.semantic_diagnostic_codes,
        samples=samples,
        excluded_records=[
            _source_record_evidence(evidence)
            for evidence in execution.rejected_evidence[:2]
        ],
    )


def _source_record_evidence(
    evidence: RuleExecutionEvidence,
) -> SourceRecordEvidenceV1:
    return SourceRecordEvidenceV1(
        record_index=evidence.record_index,
        evidence_id=evidence.evidence_id,
        source_type=evidence.source_type,
        record_tag=evidence.record_tag,
        record_attributes=evidence.record_attributes,
        visible_text=evidence.visible_text,
        field_values=SourceFieldValuesV1.model_validate(evidence.field_values),
    )


def _representative_sample_indices(
    notices: List[Dict[str, Optional[str]]],
    *,
    limit: int = 6,
) -> List[int]:
    """Choose diverse deterministic records instead of the first N records."""
    count = len(notices)
    if count <= limit:
        return list(range(count))

    title_lengths = [len(item.get("title") or "") for item in notices]
    missing_optional = [
        sum(
            not item.get(field)
            for field in ("author", "published_at", "detail_url", "external_id")
        )
        for item in notices
    ]
    priority = [
        0,
        count - 1,
        count // 2,
        max(range(count), key=title_lengths.__getitem__),
        min(range(count), key=title_lengths.__getitem__),
        max(range(count), key=missing_optional.__getitem__),
        count // 4,
        (count * 3) // 4,
    ]
    selected: List[int] = []
    for index in priority:
        if index not in selected:
            selected.append(index)
        if len(selected) >= limit:
            break
    return sorted(selected)
