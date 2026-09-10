"""Compatibility facade for the legacy deterministic extractor module."""

from dataController.scraper.extraction.deterministic import (
    ExtractionResult,
    HTML_EXTRACTOR_CONFIG_VERSION,
    extract_notices_deterministically,
    parse_json_or_jsonp,
)
from dataController.scraper.extraction.deterministic.common import (
    NUMERIC_PATH_SEGMENT_RE as _NUMERIC_PATH_SEGMENT_RE,
    normalize_date as _normalize_date,
    normalize_text as _normalize_text,
)
from dataController.scraper.extraction.deterministic.html import (
    onclick_navigation_values as _onclick_navigation_values,
    _streaming_table_candidates,
)

__all__ = [
    "ExtractionResult",
    "HTML_EXTRACTOR_CONFIG_VERSION",
    "extract_notices_deterministically",
    "parse_json_or_jsonp",
]
