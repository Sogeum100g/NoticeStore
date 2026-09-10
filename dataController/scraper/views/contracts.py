"""Internal contracts for bounded Source View diagnosis and recovery routing."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List


class SourceViewState(str, Enum):
    READY = "READY"
    REPARSE_REQUIRED = "REPARSE_REQUIRED"
    RULE_RETRY_REQUIRED = "RULE_RETRY_REQUIRED"


@dataclass(frozen=True)
class SourceEvidenceProfile:
    source_type: str
    payload_chars: int = 0
    record_candidate_count: int = 0
    record_group_count: int = 0
    title_evidence_count: int = 0
    date_evidence_count: int = 0
    anchor_count: int = 0
    navigation_evidence_count: int = 0
    data_attribute_count: int = 0
    table_count: int = 0
    list_container_count: int = 0
    embedded_data_count: int = 0
    truncated: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceViewValidation:
    state: SourceViewState
    reason_codes: List[str] = field(default_factory=list)
    evidence_loss: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "reason_codes": list(self.reason_codes),
            "evidence_loss": dict(self.evidence_loss),
        }


@dataclass(frozen=True)
class SourceViewAttempt:
    strategy: str
    payload_hash: str
    raw_evidence: SourceEvidenceProfile
    view_evidence: SourceEvidenceProfile
    validation: SourceViewValidation

    def as_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "payload_hash": self.payload_hash,
            "raw_evidence": self.raw_evidence.as_dict(),
            "view_evidence": self.view_evidence.as_dict(),
            "validation": self.validation.as_dict(),
        }
