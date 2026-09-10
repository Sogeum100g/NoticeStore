"""Cross-strategy validation and extraction evidence contracts."""

from __future__ import annotations

import re
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dataController.scraper.extraction.deterministic.models import ExtractionResult
from dataController.scraper.extraction.rules.contracts import ExtractorRuleV1


class _ExtractionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuleValidationMetrics(_ExtractionContract):
    semantic_record_count: int = Field(ge=0)
    extracted_record_count: int = Field(ge=0)
    coverage_ratio: float = Field(ge=0.0, le=1.0)
    missing_title_count: int = Field(ge=0)
    invalid_detail_url_count: int = Field(ge=0)
    invalid_date_count: int = Field(ge=0)
    duplicate_record_count: int = Field(ge=0)
    source_record_count: int = Field(default=0, ge=0)
    baseline_record_count: int = Field(default=0, ge=0)
    reference_record_count: int = Field(default=0, ge=0)
    extraction_ratio: float = Field(default=0.0, ge=0.0)


class ExtractedNoticeEvidence(_ExtractionContract):
    record_index: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=1000)
    author: Optional[str] = Field(default=None, max_length=500)
    published_at: Optional[str] = Field(default=None, max_length=100)
    detail_url: Optional[str] = Field(default=None, max_length=2000)
    external_id: Optional[str] = Field(default=None, max_length=500)
    evidence_id: str = Field(min_length=1, max_length=120)
    source_excerpt: str = Field(min_length=1, max_length=3000)


class ResultEvaluationRequestV1(_ExtractionContract):
    version: Literal[1]
    target_url: str = Field(min_length=8, max_length=2000)
    source_url: str = Field(min_length=8, max_length=2000)
    rule: ExtractorRuleV1
    metrics: RuleValidationMetrics
    samples: List[ExtractedNoticeEvidence] = Field(min_length=1, max_length=10)
    excluded_record_excerpts: List[str] = Field(default_factory=list, max_length=5)

    @field_validator("target_url", "source_url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        compact = value.strip()
        if not re.match(r"^https?://", compact, re.IGNORECASE):
            raise ValueError("HTTP(S) URL만 허용됩니다.")
        return compact


class SourceFieldValuesV1(_ExtractionContract):
    """Raw values selected from one source record before transforms."""

    title: Optional[str] = Field(default=None, max_length=1000)
    author: Optional[str] = Field(default=None, max_length=1000)
    published_at: Optional[str] = Field(default=None, max_length=1000)
    detail_url: Optional[str] = Field(default=None, max_length=1000)
    external_id: Optional[str] = Field(default=None, max_length=1000)


class SourceRecordEvidenceV1(_ExtractionContract):
    """Compact semantic evidence for one deterministically parsed record."""

    record_index: int = Field(ge=0)
    evidence_id: str = Field(min_length=1, max_length=120)
    source_type: Literal["html", "json"]
    record_tag: Optional[str] = Field(default=None, min_length=1, max_length=80)
    record_attributes: Dict[str, str] = Field(default_factory=dict, max_length=12)
    visible_text: str = Field(min_length=1, max_length=1200)
    field_values: SourceFieldValuesV1

    @field_validator("record_attributes")
    @classmethod
    def validate_record_attributes(cls, values: Dict[str, str]) -> Dict[str, str]:
        if any(
            not key
            or len(key) > 80
            or len(value) > 300
            for key, value in values.items()
        ):
            raise ValueError("레코드 속성 evidence가 허용 길이를 초과했습니다.")
        return values

    @model_validator(mode="after")
    def validate_source_shape(self) -> "SourceRecordEvidenceV1":
        if self.source_type == "html" and not self.record_tag:
            raise ValueError("HTML evidence에는 record_tag가 필요합니다.")
        if self.source_type == "json" and self.record_tag is not None:
            raise ValueError("JSON evidence에는 record_tag를 지정할 수 없습니다.")
        return self


class EvaluatedNoticeEvidenceV2(_ExtractionContract):
    title: str = Field(min_length=1, max_length=1000)
    author: Optional[str] = Field(default=None, max_length=500)
    published_at: Optional[str] = Field(default=None, max_length=100)
    detail_url: Optional[str] = Field(default=None, max_length=2000)
    external_id: Optional[str] = Field(default=None, max_length=500)
    source: SourceRecordEvidenceV1


class ResultEvaluationRequestV2(_ExtractionContract):
    """Field-oriented evaluator input without raw HTML record excerpts."""

    version: Literal[2]
    target_url: str = Field(min_length=8, max_length=2000)
    source_url: str = Field(min_length=8, max_length=2000)
    rule: ExtractorRuleV1
    metrics: RuleValidationMetrics
    semantic_diagnostic_codes: List[
        Literal["COVERAGE_MISMATCH", "OVER_EXTRACTION"]
    ] = Field(default_factory=list, max_length=2)
    samples: List[EvaluatedNoticeEvidenceV2] = Field(min_length=1, max_length=6)
    excluded_records: List[SourceRecordEvidenceV1] = Field(
        default_factory=list,
        max_length=2,
    )

    @field_validator("target_url", "source_url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        compact = value.strip()
        if not re.match(r"^https?://", compact, re.IGNORECASE):
            raise ValueError("HTTP(S) URL만 허용됩니다.")
        return compact

__all__ = [
    "EvaluatedNoticeEvidenceV2",
    "ExtractedNoticeEvidence",
    "ExtractionResult",
    "ResultEvaluationRequestV1",
    "ResultEvaluationRequestV2",
    "RuleValidationMetrics",
    "SourceFieldValuesV1",
    "SourceRecordEvidenceV1",
]
