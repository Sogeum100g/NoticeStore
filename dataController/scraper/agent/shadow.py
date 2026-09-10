"""Read-only shadow comparison between legacy and declarative extraction."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from dataController.scraper.extraction.rules.executor import execute_extractor_rule
from dataController.scraper.extraction.deterministic import (
    extract_notices_deterministically,
)
from dataController.scraper.extraction.rules.adapter import build_rule_based_candidate
from dataController.scraper.extraction.rules.hard_gate import validate_rule_execution


_PARITY_FIELDS = (
    "author",
    "published_at",
    "detail_url",
    "external_id",
)


@dataclass(frozen=True)
class ShadowComparison:
    status: str
    source_type: Optional[str]
    legacy_status: str
    legacy_count: int
    declarative_count: int
    title_parity_ratio: float
    hard_gate_passed: bool
    hard_gate_reason_codes: List[str] = field(default_factory=list)
    missing_expected_titles: List[str] = field(default_factory=list)
    prohibited_title_hits: List[str] = field(default_factory=list)
    field_mismatches: Dict[str, int] = field(default_factory=dict)
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _title_set(notices: Iterable[Dict[str, Any]]) -> set[str]:
    return {
        " ".join(str(notice.get("title") or "").split()).casefold()
        for notice in notices
        if notice.get("title")
    }


def _field_mismatches(
    legacy_notices: List[Dict[str, Any]],
    declarative_notices: List[Dict[str, Any]],
) -> Dict[str, int]:
    legacy_by_title = {
        " ".join(str(notice.get("title") or "").split()).casefold(): notice
        for notice in legacy_notices
        if notice.get("title")
    }
    mismatches = {field_name: 0 for field_name in _PARITY_FIELDS}
    for notice in declarative_notices:
        title = " ".join(str(notice.get("title") or "").split()).casefold()
        legacy = legacy_by_title.get(title)
        if legacy is None:
            continue
        for field_name in _PARITY_FIELDS:
            if (legacy.get(field_name) or None) != (notice.get(field_name) or None):
                mismatches[field_name] += 1
    return {name: count for name, count in mismatches.items() if count}


def compare_rule_based_shadow(
    raw_data: Any,
    *,
    content_type: str,
    base_url: str,
    semantic_record_count: int = 0,
    expected_titles: Optional[Iterable[str]] = None,
    prohibited_titles: Optional[Iterable[str]] = None,
) -> ShadowComparison:
    """Compare paths without an AI call or any database persistence."""
    legacy = extract_notices_deterministically(
        raw_data,
        content_type=content_type,
        base_url=base_url,
    )
    source_type = (legacy.extractor_config or {}).get("source_type")
    if legacy.status != "success":
        return ShadowComparison(
            status="legacy_failed",
            source_type=source_type,
            legacy_status=legacy.status,
            legacy_count=len(legacy.notices),
            declarative_count=0,
            title_parity_ratio=0.0,
            hard_gate_passed=False,
            reason=legacy.error or "기존 결정론적 추출이 실패했습니다.",
        )

    candidate = build_rule_based_candidate(raw_data, legacy)
    if candidate is None:
        return ShadowComparison(
            status="rule_extractor_required",
            source_type=source_type,
            legacy_status=legacy.status,
            legacy_count=len(legacy.notices),
            declarative_count=0,
            title_parity_ratio=0.0,
            hard_gate_passed=False,
            reason="기존 발견 결과를 안전한 RuleV1 후보로 변환하지 못했습니다.",
        )

    execution = execute_extractor_rule(
        raw_data,
        rule=candidate,
        base_url=base_url,
    )
    hard_gate = validate_rule_execution(
        execution,
        rule=candidate,
        semantic_record_count=semantic_record_count,
    )
    legacy_titles = _title_set(legacy.notices)
    declarative_titles = _title_set(execution.notices)
    title_parity = (
        len(legacy_titles & declarative_titles) / len(legacy_titles)
        if legacy_titles
        else 0.0
    )
    normalized_expected = {
        " ".join(str(title).split()).casefold()
        for title in (expected_titles or [])
    }
    normalized_prohibited = {
        " ".join(str(title).split()).casefold()
        for title in (prohibited_titles or [])
    }
    missing_expected = sorted(normalized_expected - declarative_titles)
    prohibited_hits = sorted(normalized_prohibited & declarative_titles)
    mismatches = _field_mismatches(legacy.notices, execution.notices)

    if missing_expected or prohibited_hits:
        status = "expectation_failed"
        reason = "업무 기대 제목 검증에 실패했습니다."
    elif not hard_gate.passed:
        status = "rule_extractor_required"
        reason = hard_gate.reason
    elif title_parity < 1.0 or len(execution.notices) != len(legacy.notices):
        status = "parity_mismatch"
        reason = "기존 추출과 선언형 추출의 제목 또는 건수가 다릅니다."
    else:
        status = "rule_based_pass"
        reason = "규칙 기반 후보가 hard gate와 제목 parity를 통과했습니다."

    return ShadowComparison(
        status=status,
        source_type=source_type,
        legacy_status=legacy.status,
        legacy_count=len(legacy.notices),
        declarative_count=len(execution.notices),
        title_parity_ratio=title_parity,
        hard_gate_passed=hard_gate.passed,
        hard_gate_reason_codes=hard_gate.reason_codes,
        missing_expected_titles=missing_expected,
        prohibited_title_hits=prohibited_hits,
        field_mismatches=mismatches,
        reason=reason,
    )
