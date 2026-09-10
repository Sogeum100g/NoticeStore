"""Compatibility facade for persistence-free extraction shadow comparison."""

from dataController.scraper.agent.shadow import (
    ShadowComparison,
    compare_rule_based_shadow,
)

__all__ = ["ShadowComparison", "compare_rule_based_shadow"]
