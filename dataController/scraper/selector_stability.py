"""Compatibility facade for the legacy selector-stability import path."""

from dataController.scraper.views.selector_stability import (
    find_volatile_html_ids,
    is_intrinsically_volatile_html_id,
    selector_uses_volatile_html_id,
)

__all__ = [
    "find_volatile_html_ids",
    "is_intrinsically_volatile_html_id",
    "selector_uses_volatile_html_id",
]
