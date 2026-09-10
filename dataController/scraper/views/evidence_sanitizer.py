"""Sanitization for bounded HTML and JSON evidence."""

from __future__ import annotations

import re
from typing import Any, Dict, Set, Tuple

from bs4 import BeautifulSoup, Comment, Tag

_HTML_DROP_NAMES = {"script", "style", "svg", "noscript", "template", "iframe"}
_HTML_ALLOWED_ATTRIBUTES = {
    "class",
    "id",
    "href",
    "title",
    "datetime",
    "itemprop",
    "role",
    "aria-label",
    "name",
    "content",
    "value",
}
_SENSITIVE_KEY_RE = re.compile(
    r"(?:password|passwd|secret|token|authorization|cookie|session|api[_-]?key)",
    re.IGNORECASE,
)

def sanitize_html_fragment(
    record: Tag,
    evidence_prefix: str,
    volatile_ids: Set[str] | None = None,
) -> Tuple[str, Set[str]]:
    clone_soup = BeautifulSoup(str(record), "lxml")
    root = clone_soup.find(record.name)
    if root is None:
        return "", set()

    for comment in clone_soup.find_all(
        string=lambda value: isinstance(value, Comment)
    ):
        comment.extract()
    for dropped in clone_soup.find_all(_HTML_DROP_NAMES):
        dropped.decompose()

    evidence_ids = {evidence_prefix}
    root["data-evidence-id"] = evidence_prefix
    evidence_index = 0
    for tag in [root, *root.find_all(True)]:
        sanitized: Dict[str, Any] = {}
        for key, value in tag.attrs.items():
            lowered = str(key).casefold()
            if (
                lowered == "id"
                and volatile_ids is not None
                and str(value) in volatile_ids
            ):
                continue
            if lowered.startswith("on") or lowered == "style":
                continue
            if lowered not in _HTML_ALLOWED_ATTRIBUTES and not lowered.startswith("data-"):
                continue
            if (
                lowered == "href"
                and str(value).strip().casefold().startswith("javascript:")
            ):
                continue
            if (
                lowered == "value"
                and _SENSITIVE_KEY_RE.search(str(tag.get("name") or ""))
            ):
                sanitized[lowered] = "[REDACTED]"
                continue
            if isinstance(value, list):
                sanitized[lowered] = [str(item)[:120] for item in value[:8]]
            else:
                sanitized[lowered] = str(value)[:500]
        tag.attrs = sanitized

        if (
            tag.name in {"a", "button", "time"}
            or tag.get("role") == "link"
            or bool(re.fullmatch(r"h[1-6]", tag.name or ""))
            or any(
                attribute in tag.attrs
                for attribute in ("title", "datetime", "href")
            )
        ):
            field_evidence_id = f"{evidence_prefix}-field-{evidence_index}"
            evidence_index += 1
            tag["data-evidence-id"] = field_evidence_id
            evidence_ids.add(field_evidence_id)

    return str(root), evidence_ids

def sanitize_html_evidence_fragment(record: Tag, evidence_prefix: str) -> str:
    """Return bounded-agent evidence without irrelevant or executable markup.

    Rule generation and result evaluation must see the same structural view of
    a record.  In particular, raw ``outerHTML`` often contains large SVG path
    data that contributes tokens but no notice semantics.  Keep selectors,
    links, dates, text, and safe data attributes while sharing the established
    structure-sampler sanitization contract.
    """
    fragment, _ = sanitize_html_fragment(record, evidence_prefix)
    return fragment

def redact_json_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "[DEPTH_LIMIT]"
    if isinstance(value, dict):
        output = {}
        for key, child in list(value.items())[:100]:
            if _SENSITIVE_KEY_RE.search(str(key)):
                output[str(key)] = "[REDACTED]"
            else:
                output[str(key)] = redact_json_value(child, depth=depth + 1)
        return output
    if isinstance(value, list):
        return [
            redact_json_value(child, depth=depth + 1)
            for child in value[:10]
        ]
    if isinstance(value, str):
        return value[:500]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:500]


def sanitize_json_evidence_value(value: Any) -> Any:
    """Expose the structure sampler's bounded JSON redaction for evaluators."""
    return redact_json_value(value)

__all__ = [
    "redact_json_value",
    "sanitize_html_evidence_fragment",
    "sanitize_html_fragment",
    "sanitize_json_evidence_value",
]
