"""Classify technical access-denial responses independently of robots.txt."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit


ACCESS_BLOCKED_HTTP_STATUSES = frozenset({401, 403, 407, 423, 429, 430, 451})

_CHALLENGE_HOSTS = frozenset(
    {
        "challenges.cloudflare.com",
    }
)
_CHALLENGE_PATH_MARKERS = (
    "/cdn-cgi/challenge-platform/",
    "/cdn-cgi/challenge/",
)
_CHALLENGE_BODY_MARKER_GROUPS = (
    ("cloudflare", "cf-chl-"),
    ("cloudflare", "challenge-platform"),
    ("cloudflare", "turnstile"),
    ("cloudflare", "just a moment"),
    ("cloudflare", "attention required"),
    ("에펨코리아 보안 시스템", "turnstile"),
)


def site_access_block_reason(
    *,
    status_code: Optional[int] = None,
    url: Optional[str] = None,
    body_text: Optional[str] = None,
) -> Optional[str]:
    """Return a diagnostic reason when the response is an access barrier.

    This intentionally does not inspect robots.txt. It only classifies an
    actual HTTP denial or a challenge document returned by the remote site.
    """

    normalized_status = status_code if isinstance(status_code, int) else None
    if normalized_status in ACCESS_BLOCKED_HTTP_STATUSES:
        return f"원격 사이트가 HTTP {status_code}로 접근을 거부했습니다."

    normalized_url = url if isinstance(url, str) else ""
    parsed = urlsplit(normalized_url)
    hostname = (parsed.hostname or "").casefold()
    path = (parsed.path or "").casefold()
    if hostname in _CHALLENGE_HOSTS or any(
        marker in path for marker in _CHALLENGE_PATH_MARKERS
    ):
        return "원격 사이트의 보안 인증 페이지가 반환되었습니다."

    lowered_body = body_text.casefold() if isinstance(body_text, str) else ""
    if any(
        all(marker.casefold() in lowered_body for marker in markers)
        for markers in _CHALLENGE_BODY_MARKER_GROUPS
    ):
        return "원격 사이트의 보안 인증 페이지가 반환되었습니다."
    return None
