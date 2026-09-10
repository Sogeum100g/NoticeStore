"""Compatibility facade for the former mixed-responsibility page module."""

from dataController.scraper.navigation.fetch_policy import (
    expand_url,
    is_crawling_allowed,
)
from dataController.scraper.sites.youtube import (
    determine_created_at,
    extract_yt_data,
    parse_youtube_community_data,
)
from dataController.scraper.views.embedded_data import (
    extract_embedded_json_data,
    extract_javascript_hydration_data,
    extract_next_data,
)
from dataController.scraper.views.page_views import (
    HtmlSourceViews,
    build_html_source_views,
    build_parser_text,
    clean_html_text,
    get_text_hash,
    normalize_string,
    preprocessing,
    remove_json_nulls,
)

__all__ = [
    "HtmlSourceViews",
    "build_html_source_views",
    "build_parser_text",
    "clean_html_text",
    "determine_created_at",
    "expand_url",
    "extract_embedded_json_data",
    "extract_javascript_hydration_data",
    "extract_next_data",
    "extract_yt_data",
    "get_text_hash",
    "is_crawling_allowed",
    "normalize_string",
    "parse_youtube_community_data",
    "preprocessing",
    "remove_json_nulls",
]
