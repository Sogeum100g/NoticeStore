"""Compatibility facade for the legacy DCInside import path."""

from dataController.scraper.sites.dcinside import (
    canonicalize_detail_url_for_target,
    gallery_list_id,
    is_recommended_list,
    preserve_list_filter,
    validate_list_response,
)

__all__ = [
    "canonicalize_detail_url_for_target",
    "gallery_list_id",
    "is_recommended_list",
    "preserve_list_filter",
    "validate_list_response",
]
