"""Canonical URL identity for notice detail links.

The normalizer is intentionally deterministic and network-free.  It removes
presentation-only differences while retaining query parameters that may be
required to identify the notice.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit


_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "referrer",
}
_REDIRECT_QUERY_KEYS = {
    "continue",
    "dest",
    "destination",
    "redirect",
    "redirecturl",
    "returnurl",
    "target",
    "targeturl",
    "url",
}
_PATH_SEGMENT_ALIASES = {
    "noticeview": "views",
    "noticeviews": "views",
    "views": "views",
}


def _http_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme.casefold() in {"http", "https"} and bool(parsed.hostname)


def _unwrap_redirect(value: str) -> str:
    current = value
    for _ in range(3):
        parsed = urlsplit(current)
        target = None
        for key, raw_value in parse_qsl(parsed.query, keep_blank_values=True):
            if key.casefold().replace("_", "") not in _REDIRECT_QUERY_KEYS:
                continue
            candidate = raw_value
            for _decode_attempt in range(2):
                if _http_url(candidate):
                    target = candidate
                    break
                decoded = unquote(candidate)
                if decoded == candidate:
                    break
                candidate = decoded
            if target:
                break
        if not target or target == current:
            return current
        current = target
    return current


def canonicalize_notice_detail_url(value: Optional[str]) -> Optional[str]:
    compact = str(value or "").strip()
    if not compact or not _http_url(compact):
        return None
    compact = _unwrap_redirect(compact)
    parsed = urlsplit(compact)

    scheme = parsed.scheme.casefold()
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if not hostname:
        return None
    port = parsed.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname

    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    segments = path.split("/")
    segments = [
        _PATH_SEGMENT_ALIASES.get(segment.casefold(), segment)
        for segment in segments
    ]
    path = "/".join(segments)

    query_items = []
    seen_items = set()
    for key, query_value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.casefold()
        if lowered.startswith("utm_") or lowered in _TRACKING_QUERY_KEYS:
            continue
        item = (key, query_value)
        if item in seen_items:
            continue
        seen_items.add(item)
        query_items.append(item)
    query_items.sort(key=lambda item: (item[0].casefold(), item[1]))

    return urlunsplit(
        (
            scheme,
            netloc,
            path,
            urlencode(query_items, doseq=True),
            "",
        )
    )
