"""Compatibility facade for extraction rule hard-gate validation."""

from dataController.scraper.extraction.rules.hard_gate import (
    HardGatePolicy,
    HardGateResult,
    build_result_evaluation_request,
    validate_rule_execution,
)

__all__ = [
    "HardGatePolicy",
    "HardGateResult",
    "build_result_evaluation_request",
    "validate_rule_execution",
]
