"""Strict JSON and JSONP decoding shared by extraction and source views."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_json_or_jsonp(text: str) -> Any:
    stripped = str(text or "").strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as original_error:
        match = re.match(
            r"^[A-Za-z_$][\w.$]*\s*\(\s*(.*)\s*\)\s*;?\s*$",
            stripped,
            re.DOTALL,
        )
        if not match:
            raise original_error
        return json.loads(match.group(1))


__all__ = ["parse_json_or_jsonp"]
