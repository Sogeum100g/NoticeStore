"""Public deterministic extraction API."""

from __future__ import annotations

import json as jsonlib
import re
from typing import Any, Dict, Optional

from dataController.scraper.extraction.deterministic.common import (
    HTML_EXTRACTOR_CONFIG_VERSION,
)
from dataController.scraper.extraction.deterministic.html import extract_html
from dataController.scraper.extraction.deterministic.json import extract_json
from dataController.scraper.extraction.deterministic.models import ExtractionResult
from dataController.scraper.views.json_decoder import parse_json_or_jsonp

def extract_notices_deterministically(
    raw_data: Any,
    *,
    content_type: str,
    base_url: str,
    extractor_config: Optional[Dict[str, Any]] = None,
) -> ExtractionResult:
    try:
        if isinstance(raw_data, (dict, list)):
            return extract_json(
                raw_data,
                base_url=base_url,
                extractor_config=extractor_config,
            )

        text = str(raw_data or "")
        looks_json_like = text.lstrip().startswith(("{", "["))
        looks_jsonp_like = bool(
            re.match(
                r"^[A-Za-z_$][\w.$]*\s*\(",
                text.lstrip(),
            )
        )
        if (
            "json" in content_type
            or "javascript" in content_type
            or looks_json_like
            or looks_jsonp_like
        ):
            return extract_json(
                parse_json_or_jsonp(text),
                base_url=base_url,
                extractor_config=extractor_config,
            )
        return extract_html(
            text,
            base_url=base_url,
            extractor_config=extractor_config,
        )
    except (jsonlib.JSONDecodeError, TypeError, ValueError) as exc:
        return ExtractionResult(
            "failed",
            [],
            extractor_config,
            None,
            0.0,
            None,
            str(exc),
        )

__all__ = [
    "ExtractionResult",
    "HTML_EXTRACTOR_CONFIG_VERSION",
    "extract_notices_deterministically",
    "parse_json_or_jsonp",
]
