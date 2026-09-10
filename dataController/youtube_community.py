import json
import re
from typing import Any, Dict, Iterator, Optional


YT_INITIAL_DATA_ASSIGNMENT_RE = re.compile(
    r"(?:\bvar\s+ytInitialData|\bytInitialData|"
    r"window\s*\[\s*['\"]ytInitialData['\"]\s*\])\s*=\s*"
)


def extract_yt_initial_data(text: str) -> Optional[Dict[str, Any]]:
    """Decode YouTube's embedded ytInitialData without a fragile JSON regex."""
    if not text:
        return None

    decoder = json.JSONDecoder()
    for match in YT_INITIAL_DATA_ASSIGNMENT_RE.finditer(text):
        try:
            value, _ = decoder.raw_decode(text, match.end())
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def iter_youtube_community_posts(value: Any) -> Iterator[Dict[str, Any]]:
    """Yield community post renderers contained anywhere in ytInitialData."""
    if isinstance(value, dict):
        post = value.get("backstagePostRenderer")
        if isinstance(post, dict):
            yield post
        for child in value.values():
            yield from iter_youtube_community_posts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_youtube_community_posts(child)
