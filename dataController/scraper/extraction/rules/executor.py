"""Deterministic executor for validated ``ExtractorRuleV1`` objects."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from dataController.scraper.extraction.deterministic.common import (
    NUMERIC_PATH_SEGMENT_RE,
    normalize_date,
)
from dataController.scraper.extraction.deterministic.html import (
    onclick_navigation_values,
)
from dataController.scraper.extraction.rules.contracts import (
    ExtractorRuleV1,
    HtmlFieldRule,
    JsonFieldRule,
)
from dataController.scraper.navigation.html import (
    is_http_detail_url,
    resolve_html_navigation_url,
)
from dataController.scraper.navigation.url_normalizer import (
    canonicalize_notice_detail_url,
)
from dataController.scraper.views.evidence_sanitizer import (
    sanitize_html_evidence_fragment,
    sanitize_json_evidence_value,
)
from dataController.scraper.views.json_decoder import parse_json_or_jsonp


@dataclass(frozen=True)
class RuleExecutionEvidence:
    record_index: int
    evidence_id: str
    source_type: str
    record_tag: Optional[str]
    record_attributes: Dict[str, str]
    visible_text: str
    field_values: Dict[str, Optional[str]]


@dataclass(frozen=True)
class RuleExecutionResult:
    status: str
    source_record_count: int
    notices: List[Dict[str, Optional[str]]]
    evidence: List[RuleExecutionEvidence]
    rejected_evidence: List[RuleExecutionEvidence]
    rejected_record_count: int
    error: Optional[str] = None


def _normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _apply_transforms(
    value: Any,
    transforms: Sequence[str],
    *,
    base_url: str,
) -> Optional[str]:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None

    transformed = str(value)
    for transform in transforms:
        if transform == "strip":
            transformed = transformed.strip()
        elif transform == "normalize_space":
            transformed = _normalize_space(transformed)
        elif transform == "date":
            return normalize_date(transformed)
        elif transform == "urljoin":
            transformed = urljoin(base_url, transformed.strip())
            if urlsplit(transformed).scheme.casefold() not in {"http", "https"}:
                return None
        elif transform == "path_id":
            matches = NUMERIC_PATH_SEGMENT_RE.findall(urlsplit(transformed).path)
            if not matches:
                return None
            transformed = matches[-1]

    return transformed.strip() or None


def _onclick_literal_value(element: Tag) -> Optional[str]:
    """Read the literal argument of a ``goView('123')``-style onclick call.

    This is the same navigation-call literal deterministic extraction
    already relies on for ``external_id`` (see ``_record_external_id``); it
    lets a converted rule keep that value even when it never appears as a
    plain ``data-*`` attribute.
    """
    for candidate in (element, *element.find_all(True)):
        values = onclick_navigation_values(candidate)
        if values:
            return values[-1]
    return None


def _select_html_field(record: Tag, rule: HtmlFieldRule) -> Any:
    selected = record if rule.selector == ":scope" else record.select_one(rule.selector)
    if selected is None:
        return None
    if rule.source in {"navigation", "onclick_literal"}:
        return selected
    if rule.source == "text":
        text_owner = copy.deepcopy(selected)
        for exclude_selector in rule.exclude_selectors:
            for excluded in text_owner.select(exclude_selector):
                excluded.decompose()
        return text_owner.get_text(" ", strip=True)
    return selected.get(rule.attribute or "")


def _path_tokens(path: str) -> List[Any]:
    tokens: List[Any] = []
    for key, index in re.findall(r"\.([A-Za-z_가-힣][A-Za-z0-9_가-힣-]*)|\[(\d+)\]", path):
        tokens.append(key if key else int(index))
    return tokens


def _json_at_path(value: Any, path: str) -> Any:
    current = value
    for token in _path_tokens(path):
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                return None
            current = current[token]
        else:
            if not isinstance(current, dict) or token not in current:
                return None
            current = current[token]
    return current


def _select_json_field(record: Dict[str, Any], rule: JsonFieldRule) -> Any:
    if rule.template is None:
        return _json_at_path(record, rule.path or "$")

    rendered = rule.template
    for name, path in rule.template_fields.items():
        value = _json_at_path(record, path)
        if value is None or isinstance(value, (dict, list, tuple, set)):
            return None
        compact = str(value).strip()
        if not compact:
            return None
        rendered = rendered.replace(f"{{{name}}}", quote(compact, safe=""))
    return rendered


def _execute_fields(
    record: Any,
    rule: ExtractorRuleV1,
    *,
    base_url: str,
    html_document: Optional[BeautifulSoup] = None,
) -> Tuple[Dict[str, Optional[str]], Dict[str, Optional[str]]]:
    notice: Dict[str, Optional[str]] = {
        "title": None,
        "author": None,
        "published_at": None,
        "detail_url": None,
        "external_id": None,
    }
    field_values: Dict[str, Optional[str]] = {}
    for field_name, field_rule in rule.fields.configured_rules().items():
        if isinstance(field_rule, HtmlFieldRule):
            raw_value = _select_html_field(record, field_rule)
            navigation_element = raw_value if isinstance(raw_value, Tag) else None
            if navigation_element is None and field_name == "detail_url":
                navigation_element = (
                    record
                    if field_rule.selector == ":scope"
                    else record.select_one(field_rule.selector)
                )
            if field_rule.source == "navigation":
                raw_value = (
                    resolve_html_navigation_url(
                        base_url,
                        navigation_element,
                        document=html_document,
                    )
                    if navigation_element is not None
                    else None
                )
            elif field_rule.source == "onclick_literal":
                raw_value = (
                    _onclick_literal_value(navigation_element)
                    if navigation_element is not None
                    else None
                )
        else:
            raw_value = _select_json_field(record, field_rule)
        transformed = _apply_transforms(
            raw_value,
            field_rule.transforms,
            base_url=base_url,
        )
        if (
            field_name == "detail_url"
            and isinstance(field_rule, HtmlFieldRule)
            and not is_http_detail_url(transformed)
            and navigation_element is not None
        ):
            transformed = resolve_html_navigation_url(
                base_url,
                navigation_element,
                document=html_document,
            )
        if field_name == "detail_url":
            transformed = canonicalize_notice_detail_url(transformed)
        evidence_value = (
            transformed
            if isinstance(field_rule, HtmlFieldRule)
            and field_rule.source == "navigation"
            else raw_value
        )
        field_values[field_name] = _compact_evidence_value(evidence_value)
        notice[field_name] = transformed
    return notice, field_values


def _compact_evidence_value(value: Any, *, max_chars: int = 1000) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple)):
        encoded = json.dumps(
            sanitize_json_evidence_value(value),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return encoded[:max_chars]
    compact = _normalize_space(value)
    return compact[:max_chars] or None


def _html_record_evidence(
    record: Tag,
    evidence_id: str,
) -> Tuple[Optional[str], Dict[str, str], str]:
    fragment = sanitize_html_evidence_fragment(record, evidence_id)
    fragment_soup = BeautifulSoup(fragment, "lxml")
    root = fragment_soup.find(record.name)
    if root is None:
        return record.name, {}, _normalize_space(record.get_text(" ", strip=True))[:1200]
    attributes: Dict[str, str] = {}
    for key, value in list(root.attrs.items())[:12]:
        if key == "data-evidence-id":
            continue
        if isinstance(value, list):
            encoded = " ".join(str(item) for item in value)
        else:
            encoded = str(value)
        attributes[str(key)[:80]] = encoded[:300]
    visible_text = _normalize_space(root.get_text(" ", strip=True))[:1200]
    return root.name, attributes, visible_text


def _json_record_evidence(record: Dict[str, Any]) -> str:
    encoded = json.dumps(
        sanitize_json_evidence_value(record),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return encoded[:1200]


def _html_records(raw_data: Any, rule: ExtractorRuleV1) -> Tuple[Any, List[Tag]]:
    if not isinstance(raw_data, str):
        raise TypeError("HTML 규칙에는 문자열 원문이 필요합니다.")
    soup = BeautifulSoup(raw_data, "lxml")
    return soup, list(soup.select(rule.record_selector or ""))


def _json_records(raw_data: Any, rule: ExtractorRuleV1) -> Tuple[None, List[Dict[str, Any]]]:
    value = parse_json_or_jsonp(raw_data) if isinstance(raw_data, str) else raw_data
    records = _json_at_path(value, rule.records_path or "$")
    if not isinstance(records, list):
        raise ValueError("records_path가 JSON 배열을 가리키지 않습니다.")
    return None, [record for record in records if isinstance(record, dict)]


def execute_extractor_rule(
    raw_data: Any,
    *,
    rule: ExtractorRuleV1,
    base_url: str,
) -> RuleExecutionResult:
    """Execute an already validated rule without invoking an AI provider."""
    parsed_owner = None
    try:
        if rule.source_type == "html":
            parsed_owner, records = _html_records(raw_data, rule)
        else:
            parsed_owner, records = _json_records(raw_data, rule)

        notices: List[Dict[str, Optional[str]]] = []
        evidence: List[RuleExecutionEvidence] = []
        rejected_evidence: List[RuleExecutionEvidence] = []
        rejected = 0
        seen_identities = set()
        for index, record in enumerate(records):
            notice, field_values = _execute_fields(
                record,
                rule,
                base_url=base_url,
                html_document=parsed_owner,
            )
            evidence_id = f"executed-record-{index}"
            if isinstance(record, Tag):
                record_tag, record_attributes, visible_text = _html_record_evidence(
                    record,
                    evidence_id,
                )
            else:
                record_tag = None
                record_attributes = {}
                visible_text = _json_record_evidence(record)
            if not visible_text:
                visible_text = " | ".join(
                    value
                    for value in field_values.values()
                    if value
                )[:1200]
            if not visible_text:
                visible_text = "(visible text 없음)"
            record_evidence = RuleExecutionEvidence(
                record_index=index,
                evidence_id=evidence_id,
                source_type=rule.source_type,
                record_tag=record_tag,
                record_attributes=record_attributes,
                visible_text=visible_text,
                field_values=field_values,
            )
            if not notice.get("title"):
                rejected += 1
                rejected_evidence.append(
                    replace(
                        record_evidence,
                        evidence_id=f"rejected-record-{index}",
                    )
                )
                continue
            if notice.get("external_id"):
                identity = ("external_id", notice["external_id"])
            elif notice.get("detail_url"):
                identity = ("detail_url", notice["detail_url"])
            else:
                identity = (
                    "content",
                    (notice.get("title") or "").casefold(),
                    notice.get("published_at"),
                )
            if identity in seen_identities:
                continue
            seen_identities.add(identity)
            notices.append(notice)
            evidence.append(record_evidence)

        return RuleExecutionResult(
            status="success" if notices else "empty",
            source_record_count=len(records),
            notices=notices,
            evidence=evidence,
            rejected_evidence=rejected_evidence,
            rejected_record_count=rejected,
        )
    except Exception as exc:
        return RuleExecutionResult(
            status="failed",
            source_record_count=0,
            notices=[],
            evidence=[],
            rejected_evidence=[],
            rejected_record_count=0,
            error=str(exc),
        )
    finally:
        if parsed_owner is not None:
            parsed_owner.decompose()
