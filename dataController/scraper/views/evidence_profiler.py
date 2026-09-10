"""Measure evidence preservation between immutable sources and bounded views."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Tuple

from bs4 import BeautifulSoup, Tag

from dataController.scraper.views.json_decoder import parse_json_or_jsonp
from dataController.scraper.views.contracts import (
    SourceEvidenceProfile,
    SourceViewAttempt,
    SourceViewState,
    SourceViewValidation,
)
from dataController.scraper.views.structure_sampler import StructureSample


_DATE_RE = re.compile(
    r"(?:20\d{2}|\d{2})[./-]\d{1,2}[./-]\d{1,2}|"
    r"\bD\s*-\s*\d+\b|오늘|어제|마감",
    re.IGNORECASE,
)
_TITLE_KEY_RE = re.compile(r"title|subject|headline|name|제목|공지명", re.I)
_HTML_TITLE_CLASS_RE = re.compile(r"(?:^|[-_])(?:title|tit|subject|headline)(?:$|[-_])", re.I)
_DATE_KEY_RE = re.compile(
    r"date|time|published|created|reg(?:istered)?|게시일|등록일|작성일",
    re.I,
)
_NAVIGATION_KEY_RE = re.compile(
    r"url|href|link|action|detail|view|id|seq|no|번호",
    re.I,
)
_EMBEDDED_DATA_RE = re.compile(
    r"__NEXT_DATA__|application/(?:ld\+)?json|"
    r"window\.[A-Za-z_$][\w$]*\s*=|self\.__next_f\.push",
    re.I,
)
_RECORD_TAGS = {"tr", "li", "article", "a", "div", "dl"}


def _html_navigation_evidence(tag: Tag) -> bool:
    href = str(tag.get("href") or "").strip().casefold()
    has_data = any(
        str(key).startswith("data-")
        and not str(key).startswith("data-evidence-")
        for key in tag.attrs
    )
    return bool(
        (href and href not in {"#", "/#", "javascript:"})
        or
        href.startswith("javascript:")
        or tag.get("onclick")
        or tag.get("formaction")
        or tag.get("form")
        or tag.get("role") == "link"
        or has_data
    )


def _html_record_groups(soup: BeautifulSoup) -> Tuple[int, int]:
    groups: List[int] = []
    for parent in soup.find_all(True):
        signatures: Dict[Tuple[str, Tuple[str, ...]], int] = defaultdict(int)
        for child in parent.find_all(recursive=False):
            if not isinstance(child, Tag) or child.name not in _RECORD_TAGS:
                continue
            text = child.get_text(" ", strip=True)
            if len(text) < 4:
                continue
            if not (
                child.find("a")
                or child.find(re.compile(r"^h[1-6]$"))
                or _html_navigation_evidence(child)
                or (
                    child.name == "tr"
                    and len(
                        child.find_all(["td", "th"], recursive=False)
                    )
                    >= 2
                    and child.find("td", recursive=False) is not None
                )
                or any(
                    _html_navigation_evidence(element)
                    for element in child.find_all(True)
                )
            ):
                continue
            classes = tuple(sorted(str(value) for value in child.get("class") or []))
            signatures[(str(child.name), classes)] += 1
        groups.extend(count for count in signatures.values() if count >= 2)
    return (max(groups, default=0), len(groups))


def profile_html_source(html: str, *, truncated: bool = False) -> SourceEvidenceProfile:
    source = str(html or "")
    soup = BeautifulSoup(source, "lxml")
    try:
        record_count, group_count = _html_record_groups(soup)
        all_tags = soup.find_all(True)
        data_attribute_count = sum(
            1
            for tag in all_tags
            for key in tag.attrs
            if str(key).startswith("data-")
            and not str(key).startswith("data-evidence-")
        )
        navigation_count = sum(
            1 for tag in all_tags if _html_navigation_evidence(tag)
        )
        title_count = sum(
            bool(tag.get_text(" ", strip=True))
            and (
                bool(re.fullmatch(r"h[1-6]", tag.name))
                or tag.get("itemprop") == "title"
                or tag.get("data-testid") == "card-title"
                or any(_HTML_TITLE_CLASS_RE.search(value) for value in tag.get("class", []))
            )
            for tag in all_tags
        )
        date_values = [soup.get_text(" ", strip=True)]
        date_values.extend(
            str(tag.get(attribute) or "")
            for tag in all_tags
            for attribute in ("datetime", "data-date", "title")
            if tag.get(attribute)
        )
        return SourceEvidenceProfile(
            source_type="html",
            payload_chars=len(source),
            record_candidate_count=record_count,
            record_group_count=group_count,
            title_evidence_count=title_count,
            date_evidence_count=sum(len(_DATE_RE.findall(value)) for value in date_values),
            anchor_count=len(soup.find_all("a")),
            navigation_evidence_count=navigation_count,
            data_attribute_count=data_attribute_count,
            table_count=len(soup.find_all("table")),
            list_container_count=len(soup.find_all(["ul", "ol", "dl"])),
            embedded_data_count=len(_EMBEDDED_DATA_RE.findall(source)),
            truncated=truncated,
        )
    finally:
        soup.decompose()


def _iter_json_arrays(value: Any, *, depth: int = 0) -> Iterable[List[Dict[str, Any]]]:
    if depth > 8:
        return
    if isinstance(value, list):
        records = [item for item in value if isinstance(item, dict)]
        if records:
            yield records
        for item in value[:10]:
            yield from _iter_json_arrays(item, depth=depth + 1)
    elif isinstance(value, dict):
        for child in list(value.values())[:100]:
            yield from _iter_json_arrays(child, depth=depth + 1)


def _json_keys(value: Any, *, depth: int = 0) -> List[str]:
    if depth > 8:
        return []
    if isinstance(value, dict):
        keys = [str(key) for key in value]
        for child in list(value.values())[:100]:
            keys.extend(_json_keys(child, depth=depth + 1))
        return keys
    if isinstance(value, list):
        keys: List[str] = []
        for child in value[:20]:
            keys.extend(_json_keys(child, depth=depth + 1))
        return keys
    return []


def profile_json_source(raw_data: Any, *, truncated: bool = False) -> SourceEvidenceProfile:
    value = parse_json_or_jsonp(raw_data) if isinstance(raw_data, str) else raw_data
    arrays = list(_iter_json_arrays(value))
    keys = _json_keys(value)
    try:
        payload_chars = len(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        payload_chars = len(str(raw_data or ""))
    return SourceEvidenceProfile(
        source_type="json",
        payload_chars=payload_chars,
        record_candidate_count=max((len(records) for records in arrays), default=0),
        record_group_count=sum(1 for records in arrays if len(records) >= 2),
        title_evidence_count=sum(bool(_TITLE_KEY_RE.search(key)) for key in keys),
        date_evidence_count=sum(bool(_DATE_KEY_RE.search(key)) for key in keys),
        navigation_evidence_count=sum(
            bool(_NAVIGATION_KEY_RE.search(key)) for key in keys
        ),
        truncated=truncated,
    )


def profile_source(raw_data: Any, *, source_type: str) -> SourceEvidenceProfile:
    if source_type == "html":
        return profile_html_source(str(raw_data or ""))
    if source_type == "json":
        return profile_json_source(raw_data)
    raise ValueError("source_type은 html 또는 json이어야 합니다.")


def profile_structure_sample(sample: StructureSample) -> SourceEvidenceProfile:
    groups = sample.payload.get("record_groups") or []
    detected_counts = [int(group.get("detected_record_count") or 0) for group in groups]
    navigation_hint_count = sum(
        len(record.get("navigation_hints") or [])
        for group in groups
        for record in group.get("records") or []
    )
    if sample.source_type == "html":
        fragments = [
            str(record.get("html") or "")
            for group in groups
            for record in group.get("records") or []
        ]
        fallback = str(sample.payload.get("fallback_html") or "")
        profiled = profile_html_source(
            "".join(fragments) or fallback,
            truncated=sample.truncated,
        )
    else:
        sampled_values = [
            record.get("value")
            for group in groups
            for record in group.get("records") or []
        ]
        value: Any = sampled_values or sample.payload.get("fallback_json")
        profiled = profile_json_source(value, truncated=sample.truncated)
    return SourceEvidenceProfile(
        **{
            **profiled.as_dict(),
            "record_candidate_count": max(detected_counts, default=0),
            "record_group_count": len(groups),
            "navigation_evidence_count": max(
                profiled.navigation_evidence_count,
                navigation_hint_count,
            ),
            "payload_chars": len(sample.to_prompt_json()),
        }
    )


def _loss(raw_count: int, view_count: int) -> float:
    if raw_count <= 0:
        return 0.0
    return max(0.0, min(1.0, (raw_count - view_count) / raw_count))


def validate_source_view(
    raw: SourceEvidenceProfile,
    view: SourceEvidenceProfile,
) -> SourceViewValidation:
    reasons: List[str] = []
    losses = {
        "records": _loss(raw.record_candidate_count, view.record_candidate_count),
        "navigation": _loss(
            raw.navigation_evidence_count,
            view.navigation_evidence_count,
        ),
        "titles": _loss(raw.title_evidence_count, view.title_evidence_count),
        "dates": _loss(raw.date_evidence_count, view.date_evidence_count),
    }
    if raw.record_candidate_count >= 2 and view.record_candidate_count == 0:
        reasons.append("RECORD_EVIDENCE_LOST")
    if (
        raw.record_candidate_count >= 2
        and raw.navigation_evidence_count >= 2
        and view.navigation_evidence_count == 0
    ):
        reasons.append("NAVIGATION_EVIDENCE_LOST")
    if (
        raw.record_candidate_count >= 2
        and raw.title_evidence_count >= 2
        and view.title_evidence_count == 0
    ):
        reasons.append("FIELD_EVIDENCE_LOST")
    if (
        raw.embedded_data_count > 0
        and view.record_candidate_count == 0
        and raw.record_candidate_count == 0
    ):
        reasons.append("EMBEDDED_DATA_NOT_EXPANDED")
    severe_loss = any(
        losses[key] >= 0.5
        for key in ("records", "navigation", "titles")
    )
    if view.truncated and (
        severe_loss
        or (
            view.record_candidate_count == 0
            and view.title_evidence_count == 0
        )
    ):
        reasons.append("VIEW_TRUNCATED")
    state = (
        SourceViewState.REPARSE_REQUIRED
        if reasons
        else SourceViewState.READY
    )
    return SourceViewValidation(state=state, reason_codes=reasons, evidence_loss=losses)


def diagnose_source_view(
    raw_data: Any,
    sample: StructureSample,
    *,
    source_type: str,
    strategy: str | None = None,
) -> SourceViewAttempt:
    raw = profile_source(raw_data, source_type=source_type)
    view = profile_structure_sample(sample)
    return SourceViewAttempt(
        strategy=strategy or sample.strategy,
        payload_hash=hashlib.sha256(
            sample.to_prompt_json().encode("utf-8")
        ).hexdigest(),
        raw_evidence=raw,
        view_evidence=view,
        validation=validate_source_view(raw, view),
    )
