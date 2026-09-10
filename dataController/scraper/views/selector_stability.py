"""Conservative checks for HTML identifiers that are unsafe to persist."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable, Set


_VALID_HTML_ID_RE = re.compile(r"^[A-Za-z_][\w-]{0,79}$")
_SELECTOR_ID_RE = re.compile(r"#([A-Za-z_][\w-]{0,79})")
_NUMBERED_ID_RE = re.compile(r"^(?P<stem>.+[-_:])(?P<number>\d+)$")
_UUID_RE = re.compile(
    r"^[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[1-5A-Fa-f0-9]{4}-"
    r"[89ABabA-Fa-f0-9]{4}-[A-Fa-f0-9]{12}$"
)
_HASH_SUFFIX_RE = re.compile(r"(?:^|[-_:])[A-Fa-f0-9]{12,}$")
_GENERATED_NUMBERED_ID_RE = re.compile(
    r"^(?:"
    r".*(?:wrapper|component|instance|widget|generated)"
    r"|react-select|ember|ext-gen|mui|headlessui|radix"
    r")[\w-]*[-_:]?\d+$",
    re.IGNORECASE,
)


def is_intrinsically_volatile_html_id(value: str) -> bool:
    """Return True for IDs whose shape strongly implies runtime generation.

    A short stable identifier such as ``notice1`` remains valid. The check is
    deliberately conservative because a numeric suffix alone does not prove
    that an ID changes between responses.
    """
    candidate = str(value or "").strip()
    if not _VALID_HTML_ID_RE.fullmatch(candidate):
        return False
    return bool(
        _UUID_RE.fullmatch(candidate)
        or _HASH_SUFFIX_RE.search(candidate)
        or _GENERATED_NUMBERED_ID_RE.fullmatch(candidate)
    )


def find_volatile_html_ids(values: Iterable[str]) -> Set[str]:
    """Find generated IDs, including numbered families in one document."""
    normalized = {
        str(value or "").strip()
        for value in values
        if _VALID_HTML_ID_RE.fullmatch(str(value or "").strip())
    }
    volatile = {
        value for value in normalized if is_intrinsically_volatile_html_id(value)
    }
    numbered_families: dict[str, Set[str]] = defaultdict(set)
    for value in normalized:
        match = _NUMBERED_ID_RE.fullmatch(value)
        if match:
            numbered_families[match.group("stem")].add(value)
    for family in numbered_families.values():
        if len(family) > 1:
            volatile.update(family)
    return volatile


def selector_uses_volatile_html_id(selector: str) -> bool:
    """Reject intrinsically generated IDs in persisted AI rules."""
    return any(
        is_intrinsically_volatile_html_id(value)
        for value in _SELECTOR_ID_RE.findall(str(selector or ""))
    )
