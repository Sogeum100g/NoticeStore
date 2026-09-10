"""DCInside list identities and mobile-to-desktop filter preservation."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup


def canonicalize_detail_url_for_target(
    detail_url: Optional[str],
    *,
    target_url: str,
    external_id: Optional[str] = None,
) -> Optional[str]:
    """Adapt a desktop gallery detail URL to its canonical mobile route."""
    if not detail_url:
        return detail_url

    target = urlsplit(target_url)
    detail = urlsplit(detail_url)
    target_parts = [part for part in target.path.split("/") if part]
    if (
        (target.hostname or "").casefold() == "m.dcinside.com"
        and len(target_parts) == 2
        and target_parts[0].casefold() == "board"
        and (detail.hostname or "").casefold().endswith(".dcinside.com")
        and detail.path.rstrip("/").casefold() in {
            "/board/view", "/mgallery/board/view", "/mini/board/view",
        }
    ):
        params = parse_qs(detail.query)
        gallery_id = (params.get("id") or [""])[0]
        post_id = (params.get("no") or [str(external_id or "")])[0]
        if (
            gallery_id == target_parts[1]
            and re.fullmatch(r"[A-Za-z0-9_-]+", gallery_id)
            and re.fullmatch(r"\d+", post_id)
        ):
            return urlunsplit(
                (
                    target.scheme,
                    target.netloc,
                    f"/board/{gallery_id}/{post_id}",
                    "",
                    "",
                )
            )
    return detail_url


def gallery_list_id(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.port not in {None, 80, 443}:
        return None
    if parsed.hostname == "m.dcinside.com":
        match = re.fullmatch(r"/board/([A-Za-z0-9_-]+)/?", parsed.path)
        return match.group(1) if match else None
    if parsed.hostname == "gall.dcinside.com" and parsed.path.rstrip("/") in {
        "/board/lists", "/mgallery/board/lists", "/mini/board/lists",
    }:
        ids = parse_qs(parsed.query).get("id", [])
        if len(ids) == 1 and re.fullmatch(r"[A-Za-z0-9_-]+", ids[0]):
            return ids[0]
    return None


def is_recommended_list(url: str) -> bool:
    if not gallery_list_id(url):
        return False
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    if parsed.hostname == "m.dcinside.com":
        return query.get("recommend") == ["1"]
    return query.get("exception_mode") == ["recommend"]


def preserve_list_filter(target_url: str, source_url: str) -> str:
    """Only adapt a list of the requested gallery; never copy arbitrary query keys."""
    if not is_recommended_list(target_url):
        return source_url
    if gallery_list_id(target_url) != gallery_list_id(source_url):
        return source_url
    if is_recommended_list(source_url):
        return source_url
    source = urlsplit(source_url)
    key, value = (
        ("recommend", "1") if source.hostname == "m.dcinside.com"
        else ("exception_mode", "recommend")
    )
    query = [(k, v) for k, v in parse_qsl(source.query, keep_blank_values=True) if k != key]
    return urlunsplit(source._replace(query=urlencode([*query, (key, value)])))


def validate_list_response(target_url: str, source_url: str, html: str) -> bool:
    """Reject redirects or ignored filters that silently broaden a recommended feed."""
    if not is_recommended_list(target_url):
        return True
    if gallery_list_id(source_url) != gallery_list_id(target_url) or not is_recommended_list(source_url):
        return False
    if urlsplit(source_url).hostname == "gall.dcinside.com":
        soup = BeautifulSoup(html, "lxml")
        try:
            return any(
                re.search(r"listKindTab\(\s*['\"]recommend['\"]", button.get("onclick", ""))
                for button in soup.select("button.on[onclick]")
            )
        finally:
            soup.decompose()
    return True
