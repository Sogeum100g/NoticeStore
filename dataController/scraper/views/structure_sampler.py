"""Bounded, structure-preserving inputs for extraction-rule generation."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

from bs4 import BeautifulSoup, Comment, Tag

from dataController.scraper.views.json_decoder import parse_json_or_jsonp
from dataController.scraper.views.selector_stability import find_volatile_html_ids
from dataController.scraper.views.evidence_sanitizer import (
    redact_json_value,
    sanitize_html_fragment,
)


_HTML_CONTAINER_NAMES = {"tr", "li", "a", "article", "section", "div", "dl"}
_HTML_CONTEXT_DROP_NAMES = {"nav", "header", "footer", "aside"}
SOURCE_VIEW_STRATEGIES = {
    "default_structure_sampler",
    "navigation_preserving",
    "table_region_preserving",
}
_DATE_HINT_RE = re.compile(
    r"(?:20\d{2}|\d{2})[./-]\d{1,2}[./-]\d{1,2}|"
    r"\bD\s*-\s*\d+\b|오늘|어제|마감",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StructureSample:
    source_type: str
    payload: Dict[str, Any]
    evidence_ids: Set[str]
    truncated: bool
    strategy: str = "default_structure_sampler"

    def to_prompt_json(self) -> str:
        return json.dumps(
            self.payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def metrics(self) -> Dict[str, Any]:
        groups = self.payload.get("record_groups") or []
        fallback_present = bool(
            self.payload.get("fallback_html")
            or self.payload.get("fallback_json") is not None
        )
        return {
            "source_type": self.source_type,
            "strategy": self.strategy,
            "group_count": len(groups),
            "detected_record_count": sum(
                int(group.get("detected_record_count") or 0)
                for group in groups
            ),
            "sampled_record_count": sum(
                len(group.get("records") or []) for group in groups
            ),
            "evidence_id_count": len(self.evidence_ids),
            "fallback_present": fallback_present,
            "truncated": self.truncated,
            "payload_chars": len(self.to_prompt_json()),
        }


def _class_tokens(tag: Tag) -> Tuple[str, ...]:
    return tuple(
        sorted(
            token
            for token in (tag.get("class") or [])
            if re.fullmatch(r"[A-Za-z_][\w-]{0,79}", str(token))
        )
    )


def _structural_signature(tag: Tag) -> Tuple[str, Tuple[str, ...], str]:
    return (
        tag.name,
        _class_tokens(tag),
        str(tag.get("role") or "").casefold(),
    )


def _region_role(parent: Tag, records: Sequence[Tag]) -> str:
    context_values = []
    current: Tag | None = parent
    for _ in range(4):
        if not isinstance(current, Tag):
            break
        context_values.extend(
            [str(current.get("id") or ""), *_class_tokens(current)]
        )
        current = current.parent if isinstance(current.parent, Tag) else None
    for record in records[:10]:
        context_values.extend(_class_tokens(record))
    context = " ".join(context_values).casefold()
    if re.search(r"\b(nav|menu|gnb|lnb|footer|sidebar)\b", context):
        return "navigation"
    if re.search(r"\b(event|banner|promotion|promo|이벤트)\b", context):
        return "event"
    if re.search(r"\b(pin|pinned|fixed|important|top-notice)\b", context):
        return "pinned"
    return "general"


def _css_token(tag: Tag, volatile_ids: Set[str] | None = None) -> str:
    tag_id = str(tag.get("id") or "").strip()
    if (
        re.fullmatch(r"[A-Za-z_][\w-]{0,79}", tag_id)
        and (volatile_ids is None or tag_id not in volatile_ids)
    ):
        return f"#{tag_id}"
    test_id = str(tag.get("data-testid") or "").strip()
    if re.fullmatch(r"[A-Za-z_][\w-]{0,79}", test_id):
        return f"{tag.name}[data-testid='{test_id}']"
    classes = _class_tokens(tag)[:2]
    suffix = "".join(f".{token}" for token in classes)
    return f"{tag.name}{suffix}"


def _base_group_selector(
    parent: Tag,
    record: Tag,
    volatile_ids: Set[str] | None = None,
) -> str:
    parent_token = _css_token(parent, volatile_ids)
    record_token = _css_token(record, volatile_ids)
    if parent.name in {"html", "body"} and not parent.get("id"):
        return record_token
    if (
        parent_token.startswith("#")
        or "[data-testid=" in parent_token
        or parent_token != parent.name
    ):
        return f"{parent_token} > {record_token}"
    current = parent.parent
    while isinstance(current, Tag) and current.name != "[document]":
        token = _css_token(current, volatile_ids)
        if token.startswith("#") or "[data-testid=" in token:
            return f"{token} {record_token}"
        current = current.parent
    return f"{parent_token} > {record_token}"


def _record_predicates(
    record: Tag,
    volatile_ids: Set[str] | None = None,
) -> Set[str]:
    """Return evidence-backed predicates that can narrow a record selector."""
    predicates: Set[str] = set()
    if record.find("a", href=True) is not None:
        predicates.add("a[href]")
    if _has_button_navigation(record):
        predicates.add("button")
    if record.find(attrs={"role": "link"}) is not None:
        predicates.add("[role='link']")
    if record.find("time", attrs={"datetime": True}) is not None:
        predicates.add("time[datetime]")
    for heading in record.find_all(re.compile(r"^h[1-6]$")):
        predicates.add(heading.name)
    for child in record.find_all(recursive=False):
        child_token = _css_token(child, volatile_ids)
        if child_token != child.name:
            predicates.add(f"> {child_token}")
    for descendant in record.find_all(True):
        descendant_token = _css_token(descendant, volatile_ids)
        if descendant_token != descendant.name and not descendant.get("id"):
            predicates.add(descendant_token)
    return predicates


def _selector_matches(soup: BeautifulSoup, selector: str) -> List[Tag]:
    return [match for match in soup.select(selector) if isinstance(match, Tag)]


def _valid_selector_matches(
    matches: Sequence[Tag],
    records: Sequence[Tag],
    *,
    allow_table_rows: bool = False,
) -> bool:
    target_ids = {id(record) for record in records}
    match_ids = {id(match) for match in matches}
    return target_ids == match_ids and all(
        _meaningful_record(match, allow_table_rows=allow_table_rows)
        and not _is_dropped_context(match)
        for match in matches
    )


def _suggested_group_selector(
    soup: BeautifulSoup,
    parent: Tag,
    records: Sequence[Tag],
    *,
    allow_table_rows: bool = False,
    volatile_ids: Set[str] | None = None,
) -> Tuple[str, str | None, List[Tag], List[Tag]]:
    """Replay and refine a selector so it does not select filtered siblings.

    Candidate grouping intentionally ignores empty separators and other
    non-record siblings. A selector built only from the parent and tag name can
    accidentally add those nodes back when the generated rule runs on the
    original DOM. Refine the selector using structure shared by every sampled
    record, then verify it against the same source document.
    """
    base_selector = _base_group_selector(parent, records[0], volatile_ids)
    base_matches = _selector_matches(soup, base_selector)
    if _valid_selector_matches(
        base_matches,
        records,
        allow_table_rows=allow_table_rows,
    ):
        return base_selector, base_selector, base_matches, []

    common_predicates = set.intersection(
        *(_record_predicates(record, volatile_ids) for record in records)
    )
    valid_candidates: List[Tuple[int, int, str, List[Tag]]] = []

    def predicate_priority(predicate: str) -> Tuple[int, int, str]:
        if predicate == "a[href]":
            category = 0
        elif predicate.startswith("> "):
            category = 1
        else:
            category = 2
        return category, len(predicate), predicate

    ordered_predicates = sorted(
        common_predicates,
        key=predicate_priority,
    )[:12]

    def collect_valid_candidates(predicate_count: int) -> None:
        for predicates in combinations(ordered_predicates, predicate_count):
            suffix = "".join(f":has({predicate})" for predicate in predicates)
            selector = f"{base_selector}{suffix}"
            matches = _selector_matches(soup, selector)
            if _valid_selector_matches(
                matches,
                records,
                allow_table_rows=allow_table_rows,
            ):
                valid_candidates.append(
                    (-len(matches), len(selector), selector, matches)
                )

    collect_valid_candidates(1)
    if not valid_candidates:
        # Bound pairwise exploration on class-heavy documents.
        ordered_predicates = ordered_predicates[:8]
        collect_valid_candidates(2)

    if not valid_candidates:
        excluded = [
            match
            for match in base_matches
            if not _meaningful_record(
                match,
                allow_table_rows=allow_table_rows,
            )
            or _is_dropped_context(match)
        ]
        return base_selector, None, [], excluded

    _, _, selector, matches = min(valid_candidates)
    match_ids = {id(match) for match in matches}
    excluded = [match for match in base_matches if id(match) not in match_ids]
    return base_selector, selector, matches, excluded


def _is_dropped_context(tag: Tag) -> bool:
    return any(
        isinstance(parent, Tag) and parent.name in _HTML_CONTEXT_DROP_NAMES
        for parent in tag.parents
    )


def _has_button_navigation(tag: Tag) -> bool:
    for button in tag.find_all("button"):
        if (
            button.get("onclick")
            or button.get("formaction")
            or button.get("form")
            or button.get("role") == "link"
            or any(str(key).startswith("data-") for key in button.attrs)
        ):
            return True
    return False


def _meaningful_record(tag: Tag, *, allow_table_rows: bool = False) -> bool:
    text = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
    if len(text) < 4:
        return False
    table_row_evidence = bool(
        allow_table_rows
        and tag.name == "tr"
        and len(tag.find_all(["td", "th"], recursive=False)) >= 2
        and tag.find("td", recursive=False) is not None
    )
    return bool(
        tag.find("a", href=True)
        or _has_button_navigation(tag)
        or tag.find(attrs={"role": "link"})
        or tag.find(re.compile(r"^h[1-6]$"))
        or any(
            str(key).startswith("data-")
            for element in [tag, *tag.find_all(True)]
            for key in element.attrs
        )
        or table_row_evidence
    )


def _group_score(records: Sequence[Tag]) -> int:
    score = min(len(records), 20) * 5
    for record in records[:5]:
        text = record.get_text(" ", strip=True)
        if record.find("a", href=True):
            score += 6
        if _has_button_navigation(record) or record.find(attrs={"role": "link"}):
            score += 6
        if record.find(re.compile(r"^h[1-6]$")):
            score += 4
        if record.find("time", attrs={"datetime": True}) or _DATE_HINT_RE.search(text):
            score += 5
        context = " ".join((record.name, *_class_tokens(record))).casefold()
        if re.search(r"notice|board|post|article|news|recruit|job|공지|채용", context):
            score += 5
    return score


def _candidate_html_groups(
    soup: BeautifulSoup,
    *,
    allow_table_rows: bool = False,
) -> List[Tuple[int, Tag, List[Tag]]]:
    candidates: List[Tuple[int, Tag, List[Tag]]] = []
    for parent in soup.find_all(True):
        grouped: Dict[Tuple[str, Tuple[str, ...], str], List[Tag]] = defaultdict(list)
        for child in parent.find_all(recursive=False):
            if (
                not isinstance(child, Tag)
                or child.name not in _HTML_CONTAINER_NAMES
                or _is_dropped_context(child)
                or not _meaningful_record(
                    child,
                    allow_table_rows=allow_table_rows,
                )
            ):
                continue
            grouped[_structural_signature(child)].append(child)
        for records in grouped.values():
            if len(records) < 2:
                continue
            role = _region_role(parent, records)
            role_score = {
                "general": 15,
                "pinned": -5,
                "event": -40,
                "navigation": -50,
            }[role]
            candidates.append(
                (_group_score(records) + role_score, parent, records)
            )

    candidates.sort(key=lambda item: (item[0], len(item[2])), reverse=True)
    selected: List[Tuple[int, Tag, List[Tag]]] = []
    used_record_ids: Set[int] = set()
    for candidate in candidates:
        record_ids = {id(record) for record in candidate[2]}
        overlap = len(record_ids & used_record_ids)
        if overlap and overlap / len(record_ids) >= 0.5:
            continue
        selected.append(candidate)
        used_record_ids.update(record_ids)
        if len(selected) >= 4:
            break
    return selected




def _navigation_hint_selector(
    element: Tag,
    record: Tag,
    volatile_ids: Set[str] | None = None,
) -> str:
    if element is record:
        return ":scope"
    element_id = str(element.get("id") or "").strip()
    if (
        re.fullmatch(r"[A-Za-z_][\w-]{0,79}", element_id)
        and (volatile_ids is None or element_id not in volatile_ids)
    ):
        return f"#{element_id}"
    classes = _class_tokens(element)[:2]
    return f"{element.name}{''.join(f'.{token}' for token in classes)}"


def _navigation_hints(
    record: Tag,
    volatile_ids: Set[str] | None = None,
) -> List[Dict[str, Any]]:
    """Describe executable navigation shapes without exposing page code."""
    hints: List[Dict[str, Any]] = []
    for element in [record, *record.find_all(True)]:
        kinds: List[str] = []
        href = str(element.get("href") or "").strip().casefold()
        if href.startswith("javascript:"):
            kinds.append("javascript_href")
        if element.get("onclick"):
            kinds.append("onclick")
        if element.get("formaction") or element.get("form"):
            kinds.append("form_navigation")
        if element.get("role") == "link":
            kinds.append("link_role")
        if not kinds:
            continue
        data_attributes = sorted(
            str(key)
            for key in element.attrs
            if str(key).startswith("data-")
        )[:12]
        hints.append(
            {
                "selector_hint": _navigation_hint_selector(
                    element,
                    record,
                    volatile_ids,
                ),
                "tag": str(element.name),
                "kinds": kinds,
                "data_attributes": data_attributes,
            }
        )
        if len(hints) >= 8:
            break
    return hints




def sample_html_structure(
    html: str,
    *,
    max_chars: int = 24000,
    max_records_per_group: int = 3,
    strategy: str = "default_structure_sampler",
) -> StructureSample:
    if strategy not in SOURCE_VIEW_STRATEGIES:
        raise ValueError(f"허용되지 않은 Source View 전략입니다: {strategy}")
    soup = BeautifulSoup(html, "lxml")
    evidence_ids: Set[str] = set()
    groups_payload: List[Dict[str, Any]] = []
    used_chars = 0
    truncated = False
    try:
        volatile_ids = find_volatile_html_ids(
            str(tag.get("id") or "")
            for tag in soup.find_all(id=True)
        )
        allow_table_rows = strategy == "table_region_preserving"
        groups = _candidate_html_groups(
            soup,
            allow_table_rows=allow_table_rows,
        )
        for group_index, (_, parent, records) in enumerate(groups):
            group_id = f"html-group-{group_index}"
            (
                base_selector,
                suggested_selector,
                selector_matches,
                excluded_matches,
            ) = _suggested_group_selector(
                soup,
                parent,
                records,
                allow_table_rows=allow_table_rows,
                volatile_ids=volatile_ids,
            )
            sampled_records = []
            for record_index, record in enumerate(records[:max_records_per_group]):
                record_id = f"{group_id}-record-{record_index}"
                fragment, fragment_ids = sanitize_html_fragment(
                    record,
                    record_id,
                    volatile_ids,
                )
                if not fragment:
                    continue
                if used_chars + len(fragment) > max_chars:
                    truncated = True
                    break
                used_chars += len(fragment)
                evidence_ids.update(fragment_ids)
                sampled_records.append(
                    {
                        "evidence_id": record_id,
                        "html": fragment,
                        **(
                            {
                                "navigation_hints": _navigation_hints(
                                    record,
                                    volatile_ids,
                                )
                            }
                            if strategy == "navigation_preserving"
                            else {}
                        ),
                    }
                )
            excluded_records = []
            for excluded_index, record in enumerate(excluded_matches[:2]):
                record_id = f"{group_id}-excluded-{excluded_index}"
                fragment, fragment_ids = sanitize_html_fragment(
                    record,
                    record_id,
                    volatile_ids,
                )
                if not fragment:
                    continue
                if used_chars + len(fragment) > max_chars:
                    truncated = True
                    break
                used_chars += len(fragment)
                evidence_ids.update(fragment_ids)
                excluded_records.append(
                    {
                        "evidence_id": record_id,
                        "html": fragment,
                    }
                )
            if sampled_records:
                evidence_ids.add(group_id)
                groups_payload.append(
                    {
                        "evidence_id": group_id,
                        "region_role": _region_role(parent, records),
                        "suggested_selector": suggested_selector,
                        "detected_record_count": len(records),
                        "selector_validation": {
                            "status": (
                                "passed"
                                if suggested_selector == base_selector
                                else "refined"
                                if suggested_selector is not None
                                else "mismatch"
                            ),
                            "base_selector": base_selector,
                            "base_match_count": len(
                                _selector_matches(soup, base_selector)
                            ),
                            "suggested_match_count": len(selector_matches),
                            "excluded_match_count": len(excluded_matches),
                        },
                        "records": sampled_records,
                        "excluded_records": excluded_records,
                    }
                )
            if used_chars >= max_chars:
                truncated = True
                break

        fallback_html = None
        if not groups_payload:
            fallback = soup.find("main") or soup.find("body")
            if fallback is not None:
                fallback_html, fallback_ids = sanitize_html_fragment(
                    fallback,
                    "html-fallback-0",
                    volatile_ids,
                )
                fallback_length = len(fallback_html)
                fallback_html = fallback_html[:max_chars]
                evidence_ids.update(fallback_ids)
                truncated = fallback_length > max_chars

        payload = {
            "version": 1,
            "source_type": "html",
            "untrusted_content": True,
            "selector_stability": {
                "omitted_volatile_ids": sorted(volatile_ids)[:20],
            },
            "record_groups": groups_payload,
            "fallback_html": fallback_html,
            "truncated": truncated,
        }
        return StructureSample(
            "html",
            payload,
            evidence_ids,
            truncated,
            strategy,
        )
    finally:
        soup.decompose()


def _iter_json_arrays(
    value: Any,
    *,
    path: str = "$",
    depth: int = 0,
) -> Iterable[Tuple[str, List[Dict[str, Any]]]]:
    if depth > 8:
        return
    if isinstance(value, list):
        records = [item for item in value if isinstance(item, dict)]
        if records:
            yield path, records
        for index, item in enumerate(value[:5]):
            yield from _iter_json_arrays(item, path=f"{path}[{index}]", depth=depth + 1)
    elif isinstance(value, dict):
        for key, child in list(value.items())[:100]:
            if not re.fullmatch(r"[A-Za-z_가-힣][A-Za-z0-9_가-힣-]*", str(key)):
                continue
            yield from _iter_json_arrays(
                child,
                path=f"{path}.{key}",
                depth=depth + 1,
            )




def _json_group_score(records: Sequence[Dict[str, Any]]) -> int:
    scalar_keys = sum(
        1
        for record in records[:3]
        for value in record.values()
        if value is None or isinstance(value, (str, int, float, bool))
    )
    return min(len(records), 20) * 5 + min(scalar_keys, 30)


def sample_json_structure(
    raw_data: Any,
    *,
    max_chars: int = 24000,
    max_records_per_group: int = 3,
) -> StructureSample:
    value = parse_json_or_jsonp(raw_data) if isinstance(raw_data, str) else raw_data
    groups = list(_iter_json_arrays(value))
    groups.sort(key=lambda item: _json_group_score(item[1]), reverse=True)

    evidence_ids: Set[str] = set()
    groups_payload: List[Dict[str, Any]] = []
    used_chars = 0
    truncated = False
    for group_index, (path, records) in enumerate(groups[:4]):
        group_id = f"json-group-{group_index}"
        sampled_records = []
        for record_index, record in enumerate(records[:max_records_per_group]):
            record_id = f"{group_id}-record-{record_index}"
            redacted = redact_json_value(record)
            encoded = json.dumps(
                redacted,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if used_chars + len(encoded) > max_chars:
                truncated = True
                break
            used_chars += len(encoded)
            evidence_ids.add(record_id)
            sampled_records.append(
                {
                    "evidence_id": record_id,
                    "value": redacted,
                }
            )
        if sampled_records:
            evidence_ids.add(group_id)
            groups_payload.append(
                {
                    "evidence_id": group_id,
                    "records_path": path,
                    "detected_record_count": len(records),
                    "records": sampled_records,
                }
            )
        if used_chars >= max_chars:
            truncated = True
            break

    fallback_json = None
    if not groups_payload:
        fallback_json = redact_json_value(value)
        encoded = json.dumps(
            fallback_json,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(encoded) > max_chars:
            fallback_json = {"summary": encoded[:max_chars]}
            truncated = True
        evidence_ids.add("json-fallback-0")

    payload = {
        "version": 1,
        "source_type": "json",
        "untrusted_content": True,
        "record_groups": groups_payload,
        "fallback_json": fallback_json,
        "truncated": truncated,
    }
    return StructureSample("json", payload, evidence_ids, truncated)


def sample_source_structure(
    raw_data: Any,
    *,
    source_type: str,
    max_chars: int = 24000,
    strategy: str = "default_structure_sampler",
) -> StructureSample:
    if source_type == "html":
        return sample_html_structure(
            str(raw_data),
            max_chars=max_chars,
            strategy=strategy,
        )
    if source_type == "json":
        if strategy != "default_structure_sampler":
            raise ValueError(
                f"JSON에 적용할 수 없는 Source View 전략입니다: {strategy}"
            )
        return sample_json_structure(raw_data, max_chars=max_chars)
    raise ValueError("source_type은 html 또는 json이어야 합니다.")
