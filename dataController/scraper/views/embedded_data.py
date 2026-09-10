"""Safe discovery of embedded JSON and hydration records in HTML."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bs4 import BeautifulSoup

def extract_next_data(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
    script_tag = soup.find("script", id="__NEXT_DATA__")
    if script_tag:
        try:
            return json.loads(script_tag.string or "")
        except (json.JSONDecodeError, TypeError):
            return None
    return None


_EMBEDDED_TITLE_KEY_RE = re.compile(
    r"title|subject|headline|(?:^|[_-])name(?:$|[_-])|제목|공지명",
    re.IGNORECASE,
)
_EMBEDDED_SUPPORT_KEY_RE = re.compile(
    r"date|time|published|created|게시일|등록일|작성일",
    re.IGNORECASE,
)


def _embedded_json_record_groups(
    value: Any,
    *,
    depth: int = 0,
) -> Iterable[Tuple[int, int, int]]:
    if depth > 8:
        return
    if isinstance(value, list):
        records = [item for item in value if isinstance(item, dict)]
        if len(records) >= 2:
            keys = {
                str(key)
                for record in records[:10]
                for key in record
            }
            title_hits = sum(bool(_EMBEDDED_TITLE_KEY_RE.search(key)) for key in keys)
            support_hits = sum(
                bool(_EMBEDDED_SUPPORT_KEY_RE.search(key)) for key in keys
            )
            if title_hits and support_hits:
                yield len(records), title_hits, support_hits
        for child in value[:10]:
            yield from _embedded_json_record_groups(child, depth=depth + 1)
    elif isinstance(value, dict):
        for child in list(value.values())[:100]:
            yield from _embedded_json_record_groups(child, depth=depth + 1)


def extract_embedded_json_data(soup: BeautifulSoup) -> Optional[Any]:
    """Return conservative hydration JSON containing repeated records.

    JSON-LD is intentionally excluded because SEO item lists and site-wide
    navigation frequently resemble notice collections. The selected payload
    must contain at least two object records with both a title-like key and a
    publication-date-like key. Identifier/link-only menu data is insufficient.
    """
    candidates: List[Tuple[Tuple[int, int, int], Any]] = []
    for script_tag in soup.find_all("script"):
        script_type = str(script_tag.get("type") or "").split(";", 1)[0]
        if script_type.strip().casefold() != "application/json":
            continue
        raw_value = script_tag.string or script_tag.get_text("", strip=False)
        if not raw_value or len(raw_value) > 5 * 1024 * 1024:
            continue
        try:
            value = json.loads(raw_value)
        except (json.JSONDecodeError, TypeError):
            continue
        evidence = max(
            _embedded_json_record_groups(value),
            default=None,
        )
        if evidence is not None:
            candidates.append((evidence, value))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


_WINDOW_STATE_ASSIGN_RE = re.compile(
    r"(?:window|globalThis)\s*(?:\.\s*[A-Za-z_$][\w$]*|"
    r"\[\s*['\"][^'\"]{1,120}['\"]\s*\])\s*=",
)
_NEXT_FLIGHT_PUSH_RE = re.compile(r"self\s*\.\s*__next_f\s*\.\s*push\s*\(")


def _raw_json_at(source: str, start: int) -> Optional[Any]:
    compact = source[start:].lstrip()
    if not compact:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(compact)
        return value
    except (json.JSONDecodeError, TypeError):
        return None


def _json_fragments_from_string(value: str) -> Iterable[Any]:
    compact = value.strip()
    if not compact or len(compact) > 5 * 1024 * 1024:
        return
    decoded = _raw_json_at(compact, 0)
    if decoded is not None:
        yield decoded
    decoder = json.JSONDecoder()
    yielded = 0
    for index, char in enumerate(compact):
        if char not in "[{":
            continue
        try:
            candidate, _ = decoder.raw_decode(compact[index:])
        except json.JSONDecodeError:
            continue
        yield candidate
        yielded += 1
        if yielded >= 50:
            break


def _nested_string_json_values(
    value: Any,
    *,
    budget: List[int],
    depth: int = 0,
) -> Iterable[Any]:
    if depth > 6 or budget[0] <= 0:
        return
    if isinstance(value, str):
        for candidate in _json_fragments_from_string(value):
            if budget[0] <= 0:
                break
            budget[0] -= 1
            yield candidate
            yield from _nested_string_json_values(
                candidate,
                budget=budget,
                depth=depth + 1,
            )
    elif isinstance(value, list):
        for child in value[:50]:
            yield from _nested_string_json_values(
                child,
                budget=budget,
                depth=depth + 1,
            )
    elif isinstance(value, dict):
        for child in list(value.values())[:100]:
            yield from _nested_string_json_values(
                child,
                budget=budget,
                depth=depth + 1,
            )


def extract_javascript_hydration_data(soup: BeautifulSoup) -> Optional[Any]:
    """Decode allowlisted JavaScript hydration containers without evaluation.

    Only strict JSON assigned to ``window/globalThis`` variables, strict
    ``JSON.parse`` string literals, and strict JSON arguments passed to
    ``self.__next_f.push`` are considered. JavaScript expressions, functions,
    concatenation, and object literals with non-JSON syntax fail closed.
    """
    candidates: List[Tuple[Tuple[int, int, int], Any]] = []
    for script_tag in soup.find_all("script")[:200]:
        script_type = str(script_tag.get("type") or "").split(";", 1)[0]
        if script_type.strip().casefold() in {
            "application/json",
            "application/ld+json",
        }:
            continue
        source = script_tag.string or script_tag.get_text("", strip=False)
        if not source or len(source) > 5 * 1024 * 1024:
            continue

        roots: List[Any] = []
        for match in _WINDOW_STATE_ASSIGN_RE.finditer(source):
            value_start = match.end()
            suffix = source[value_start:].lstrip()
            if suffix.startswith("JSON.parse("):
                parsed_argument = _raw_json_at(
                    suffix,
                    len("JSON.parse("),
                )
                if isinstance(parsed_argument, str):
                    parsed_argument = _raw_json_at(parsed_argument, 0)
                if parsed_argument is not None:
                    roots.append(parsed_argument)
                continue
            parsed = _raw_json_at(source, value_start)
            if parsed is not None:
                roots.append(parsed)

        for match in _NEXT_FLIGHT_PUSH_RE.finditer(source):
            parsed = _raw_json_at(source, match.end())
            if parsed is not None:
                roots.append(parsed)

        fragment_budget = [200]
        for root in roots[:100]:
            values = [root]
            values.extend(
                _nested_string_json_values(
                    root,
                    budget=fragment_budget,
                )
            )
            for value in values:
                evidence = max(
                    _embedded_json_record_groups(value),
                    default=None,
                )
                if evidence is not None:
                    candidates.append((evidence, value))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]



__all__ = [
    "extract_embedded_json_data",
    "extract_javascript_hydration_data",
    "extract_next_data",
]
