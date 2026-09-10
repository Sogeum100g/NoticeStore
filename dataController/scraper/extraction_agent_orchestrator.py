"""Compatibility facade for extraction-rule activation orchestration."""

import sys

from dataController.scraper.agent import orchestrator as _implementation
from dataController.scraper.agent.orchestrator import (
    RuleActivationResult,
    activate_candidate_rule,
)

__all__ = ["RuleActivationResult", "activate_candidate_rule"]

_implementation.__all__ = __all__
sys.modules[__name__] = _implementation
