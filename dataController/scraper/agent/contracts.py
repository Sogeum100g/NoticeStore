"""Structured contracts used only by view selection and result evaluation."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dataController.scraper.extraction.rules.contracts import (
    FieldName,
)
from dataController.scraper.extraction.contracts import (
    EvaluatedNoticeEvidenceV2,
    ExtractedNoticeEvidence,
    ResultEvaluationRequestV1,
    ResultEvaluationRequestV2,
    RuleValidationMetrics,
    SourceFieldValuesV1,
    SourceRecordEvidenceV1,
)

SourceViewStrategy = Literal[
    "default_structure_sampler",
    "navigation_preserving",
    "table_region_preserving",
]
MIN_RESULT_PASS_CONFIDENCE = 0.8


class _AgentContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceViewGroupEvidenceV1(_AgentContract):
    evidence_id: str = Field(min_length=1, max_length=120)
    region_role: Optional[str] = Field(default=None, max_length=40)
    selector_or_path: Optional[str] = Field(default=None, max_length=500)
    detected_record_count: int = Field(ge=0)


class SourceViewCandidateV1(_AgentContract):
    strategy: SourceViewStrategy
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    validation_state: Literal["READY", "REPARSE_REQUIRED"]
    reason_codes: List[str] = Field(default_factory=list, max_length=12)
    evidence_loss: Dict[str, float] = Field(default_factory=dict, max_length=8)
    payload_chars: int = Field(ge=0)
    truncated: bool
    groups: List[SourceViewGroupEvidenceV1] = Field(
        default_factory=list,
        max_length=4,
    )

    @field_validator("evidence_loss")
    @classmethod
    def validate_evidence_loss(cls, values: Dict[str, float]) -> Dict[str, float]:
        if any(not 0.0 <= value <= 1.0 for value in values.values()):
            raise ValueError("evidence loss는 0~1 범위여야 합니다.")
        return values


class SourceViewSelectionRequestV1(_AgentContract):
    version: Literal[1]
    candidates: List[SourceViewCandidateV1] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def validate_candidates(self) -> "SourceViewSelectionRequestV1":
        identities = {
            (candidate.strategy, candidate.payload_hash)
            for candidate in self.candidates
        }
        if len(identities) != len(self.candidates):
            raise ValueError("Source View 후보는 중복될 수 없습니다.")
        return self


class SourceViewSelectionV1(_AgentContract):
    version: Literal[1]
    strategy: SourceViewStrategy
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confidence: float = Field(ge=0.8, le=1.0)
    reason: str = Field(min_length=1, max_length=500)


ResultReasonCode = Literal[
    "WRONG_CONTENT_REGION",
    "NON_NOTICE_CONTENT",
    "RECORD_BOUNDARY_MISMATCH",
    "TITLE_MISMATCH",
    "AUTHOR_MISMATCH",
    "DATE_MISMATCH",
    "DETAIL_URL_MISMATCH",
    "COVERAGE_MISMATCH",
    "DUPLICATE_RECORDS",
    "INSUFFICIENT_EVIDENCE",
    "OTHER",
]




class ResultEvaluationV1(_AgentContract):
    """Binary activation decision. Low confidence must fail closed."""

    version: Literal[1]
    decision: Literal["pass", "fail"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason_codes: List[ResultReasonCode] = Field(default_factory=list, max_length=8)
    affected_fields: List[FieldName] = Field(default_factory=list, max_length=5)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_decision_evidence(self) -> "ResultEvaluationV1":
        if self.decision == "pass" and self.reason_codes:
            raise ValueError("pass에는 failure reason code를 포함할 수 없습니다.")
        if self.decision == "fail" and not self.reason_codes:
            raise ValueError("fail에는 하나 이상의 reason code가 필요합니다.")
        if (
            self.decision == "pass"
            and self.confidence < MIN_RESULT_PASS_CONFIDENCE
        ):
            raise ValueError("낮은 신뢰도의 평가는 pass로 활성화할 수 없습니다.")
        return self


class ResultEvaluationV2(ResultEvaluationV1):
    """Evaluation output paired with ``ResultEvaluationRequestV2``."""

    version: Literal[2]



def result_evaluation_json_schema() -> Dict[str, object]:
    return ResultEvaluationV1.model_json_schema()


__all__ = [
    "EvaluatedNoticeEvidenceV2",
    "ExtractedNoticeEvidence",
    "MIN_RESULT_PASS_CONFIDENCE",
    "ResultEvaluationRequestV1",
    "ResultEvaluationRequestV2",
    "ResultEvaluationV1",
    "ResultEvaluationV2",
    "ResultReasonCode",
    "RuleValidationMetrics",
    "SourceFieldValuesV1",
    "SourceRecordEvidenceV1",
    "SourceViewCandidateV1",
    "SourceViewGroupEvidenceV1",
    "SourceViewSelectionRequestV1",
    "SourceViewSelectionV1",
    "SourceViewStrategy",
    "result_evaluation_json_schema",
]
