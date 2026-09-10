"""Compatibility facade for the legacy HTML-navigation import path."""

from dataController.scraper.navigation.html import (
    has_navigation_metadata,
    is_http_detail_url,
    is_placeholder_navigation,
    resolve_html_navigation_url,
)

__all__ = [
    "has_navigation_metadata",
    "is_http_detail_url",
    "is_placeholder_navigation",
    "resolve_html_navigation_url",
]
