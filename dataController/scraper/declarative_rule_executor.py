"""Compatibility facade for declarative rule execution."""

from dataController.scraper.extraction.rules.executor import (
    RuleExecutionEvidence,
    RuleExecutionResult,
    execute_extractor_rule,
)

__all__ = [
    "RuleExecutionEvidence",
    "RuleExecutionResult",
    "execute_extractor_rule",
]
