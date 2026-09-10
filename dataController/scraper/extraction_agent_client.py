"""Compatibility facade for the structured extraction-agent client."""

import sys

from dataController.scraper.agent import client as _implementation
from dataController.scraper.agent.client import (
    StructuredAgentResponse,
    evaluate_extraction_result,
    evaluate_extraction_result_sync,
    generate_extractor_rule,
    generate_extractor_rule_sync,
    select_source_view,
    select_source_view_sync,
)

__all__ = [
    "StructuredAgentResponse",
    "evaluate_extraction_result",
    "evaluate_extraction_result_sync",
    "generate_extractor_rule",
    "generate_extractor_rule_sync",
    "select_source_view",
    "select_source_view_sync",
]

# Preserve legacy unittest.mock.patch targets while the implementation lives
# at the canonical package path.
_implementation.__all__ = __all__
sys.modules[__name__] = _implementation
