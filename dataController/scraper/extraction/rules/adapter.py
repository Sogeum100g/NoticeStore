"""Convert successful legacy deterministic discoveries into Rule V1 candidates."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional
from urllib.parse import quote, urlsplit

import soupsieve
from bs4 import BeautifulSoup, NavigableString, Tag

from dataController.scraper.extraction.deterministic.common import (
    NUMERIC_PATH_SEGMENT_RE,
    normalize_date,
)
from dataController.scraper.extraction.deterministic.html import (
    onclick_navigation_values,
)
from dataController.scraper.extraction.deterministic.models import ExtractionResult
from dataController.scraper.extraction.rules.contracts import ExtractorRuleV1
from dataController.scraper.navigation.html import is_placeholder_navigation


_JSON_KEY_RE = re.compile(r"^[A-Za-z_가-힣][A-Za-z0-9_가-힣-]*$")
_JSON_KEY_PATH_RE = re.compile(
    r"^[A-Za-z_가-힣][A-Za-z0-9_가-힣-]*(?:\.[A-Za-z_가-힣][A-Za-z0-9_가-힣-]*)*$"
)
_SAFE_DATA_ATTRIBUTE_RE = re.compile(r"^data-[a-z0-9][a-z0-9_-]*$")


def _detail_url_template(result: ExtractionResult) -> Optional[str]:
    """Infer one stable URL template from deterministic notice results.

    Two matching records are required so a coincidental substring in one URL
    cannot become an active declarative rule.
    """
    templates = []
    for notice in result.notices[:20]:
        detail_url = str(notice.get("detail_url") or "").strip()
        external_id = str(notice.get("external_id") or "").strip()
        if not detail_url or not external_id:
            continue
        if urlsplit(detail_url).scheme.casefold() not in {"http", "https"}:
            continue

        template = None
        for token in dict.fromkeys((external_id, quote(external_id, safe=""))):
            if token and token in detail_url:
                template = detail_url.replace(token, "{external_id}", 1)
                break
        if template is not None:
            templates.append(template)

    if len(templates) < 2 or len(set(templates)) != 1:
        return None
    return templates[0]


def _json_candidate(result: ExtractionResult) -> Optional[ExtractorRuleV1]:
    config = result.extractor_config or {}
    records_path = config.get("records_path")
    mappings = config.get("fields") or {}
    title_key = mappings.get("title")
    if not records_path or not title_key or not _JSON_KEY_PATH_RE.fullmatch(title_key):
        return None

    fields: Dict[str, Dict[str, Any]] = {}
    for output_name in (
        "title",
        "author",
        "published_at",
        "detail_url",
        "external_id",
    ):
        source_key = mappings.get(output_name)
        if not source_key or not _JSON_KEY_PATH_RE.fullmatch(source_key):
            continue
        transforms = ["normalize_space"]
        if output_name == "published_at":
            transforms.append("date")
        elif output_name == "detail_url":
            transforms.append("urljoin")
        fields[output_name] = {
            "kind": "json",
            "path": f"$.{source_key}",
            "transforms": transforms,
        }

    if "detail_url" not in fields:
        external_id_key = mappings.get("external_id")
        detail_template = _detail_url_template(result)
        if (
            detail_template
            and external_id_key
            and _JSON_KEY_RE.fullmatch(external_id_key)
        ):
            fields["detail_url"] = {
                "kind": "json",
                "template": detail_template,
                "template_fields": {"external_id": f"$.{external_id_key}"},
                "transforms": [],
            }

    return ExtractorRuleV1.model_validate(
        {
            "version": 1,
            "source_type": "json",
            "records_path": records_path,
            "fields": fields,
            "evidence_ids": ["legacy-deterministic-json"],
        }
    )


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _selector_for_tag(tag: Tag, record: Tag) -> str:
    if tag is record:
        return ":scope"
    candidates = []
    tag_name = tag.name or "*"
    if tag.get("id"):
        candidates.append(f"{tag_name}#{soupsieve.escape(str(tag['id']))}")
    classes = [str(value) for value in tag.get("class", []) if value]
    class_suffix = "".join(f".{soupsieve.escape(value)}" for value in classes[:3])
    if classes:
        candidates.append(tag_name + class_suffix)
    same_name_siblings = [
        sibling
        for sibling in tag.parent.find_all(tag_name, recursive=False)
    ]
    if len(same_name_siblings) > 1:
        position = same_name_siblings.index(tag) + 1
        # A shared class alone (e.g. several sibling <span class="list">
        # label/value pairs) is often not unique within the record, and a
        # bare nth-of-type alone can match an unrelated tag elsewhere in the
        # record whose own parent happens to share that position. Combining
        # both narrows to elements that are simultaneously "this class" and
        # "this position among same-name siblings", which is unique far more
        # often than either alone.
        if classes:
            candidates.append(f"{tag_name}{class_suffix}:nth-of-type({position})")
        candidates.append(f"{tag_name}:nth-of-type({position})")
    candidates.append(tag_name)
    for candidate in candidates:
        try:
            if record.select_one(candidate) is tag:
                return candidate
        except Exception:
            continue
    return candidates[-2] if len(candidates) > 1 else tag_name


def _text_tag(record: Tag, expected: str) -> Optional[Tag]:
    normalized_expected = _normalized(expected)
    if not normalized_expected:
        return None
    matches = []
    for tag in record.find_all(True):
        full_text = _normalized(tag.get_text(" ", strip=True))
        direct_text = _normalized(
            " ".join(
                str(child)
                for child in tag.children
                if isinstance(child, NavigableString)
            )
        )
        if full_text == normalized_expected or direct_text == normalized_expected:
            matches.append(tag)
    if not matches:
        return None
    priority = {"a": 0, "h1": 1, "h2": 1, "h3": 1, "h4": 1, "td": 2}
    return min(matches, key=lambda tag: (priority.get(tag.name, 5), len(str(tag))))


def _title_exclude_selectors(title_tag: Tag, expected: str) -> list[str]:
    full_text = _normalized(title_tag.get_text(" ", strip=True))
    direct_text = _normalized(
        " ".join(
            str(child)
            for child in title_tag.children
            if isinstance(child, NavigableString)
        )
    )
    if full_text == _normalized(expected) or direct_text != _normalized(expected):
        return []
    return [
        _selector_for_tag(child, title_tag)
        for child in title_tag.find_all(True, recursive=False)
        if _normalized(child.get_text(" ", strip=True))
    ][:5]


def _date_rule(record: Tag, expected: str) -> Optional[Dict[str, Any]]:
    if not expected:
        return None
    for tag in [record, *record.find_all(True)]:
        for attribute in ("datetime", "title", "data-date", "data-datetime"):
            value = tag.get(attribute)
            if value and normalize_date(value) == expected:
                return {
                    "kind": "html",
                    "selector": _selector_for_tag(tag, record),
                    "source": "attribute",
                    "attribute": attribute,
                    "transforms": ["strip", "date"],
                }
    text_matches = [
        tag
        for tag in record.find_all(True)
        if normalize_date(tag.get_text(" ", strip=True)) == expected
    ]
    if text_matches:
        # A wrapper tag's full text can coincidentally still parse to the
        # right date (e.g. an <a> that also contains the title and view
        # count). Prefer the smallest matching tag so the rule targets the
        # actual date element instead of the whole record.
        tag = min(text_matches, key=lambda item: len(str(item)))
        return {
            "kind": "html",
            "selector": _selector_for_tag(tag, record),
            "source": "text",
            "transforms": ["normalize_space", "date"],
        }
    return None


def _html_candidate(raw_data: Any, result: ExtractionResult) -> Optional[ExtractorRuleV1]:
    if not isinstance(raw_data, str) or not result.notices:
        return None
    config = result.extractor_config or {}
    record_selector = config.get("record_css")
    if not record_selector:
        return None

    soup = BeautifulSoup(raw_data, "lxml")
    try:
        records = soup.select(record_selector)
        if not records:
            return None
        first_notice = result.notices[0]
        first_record = None
        title_tag = None
        for record in records[:50]:
            matched = _text_tag(record, first_notice.get("title") or "")
            if matched is not None:
                first_record, title_tag = record, matched
                break
        if first_record is None or title_tag is None:
            return None

        title_selector = _selector_for_tag(title_tag, first_record)
        fields: Dict[str, Dict[str, Any]] = {
            "title": {
                "kind": "html",
                "selector": title_selector,
                "source": "text",
                "exclude_selectors": _title_exclude_selectors(
                    title_tag,
                    first_notice.get("title") or "",
                ),
                "transforms": ["normalize_space"],
            }
        }

        detail_url = first_notice.get("detail_url")
        if detail_url:
            anchor = (
                title_tag
                if title_tag.name in {"a", "button"}
                else title_tag.find(["a", "button"])
            )
            if anchor is None:
                anchor = title_tag.find_parent(["a", "button"])
            if anchor is not None:
                if is_placeholder_navigation(anchor):
                    fields["detail_url"] = {
                        "kind": "html",
                        "selector": _selector_for_tag(anchor, first_record),
                        "source": "navigation",
                        "transforms": [],
                    }
                elif anchor.get("href"):
                    fields["detail_url"] = {
                        "kind": "html",
                        "selector": _selector_for_tag(anchor, first_record),
                        "source": "attribute",
                        "attribute": "href",
                        "transforms": ["strip", "urljoin"],
                    }

        author = first_notice.get("author")
        author_tag = _text_tag(first_record, author or "")
        if author_tag is not None and author_tag is not title_tag:
            fields["author"] = {
                "kind": "html",
                "selector": _selector_for_tag(author_tag, first_record),
                "source": "text",
                "transforms": ["normalize_space"],
            }

        date_field = _date_rule(
            first_record,
            first_notice.get("published_at") or "",
        )
        if date_field:
            fields["published_at"] = date_field

        external_id = first_notice.get("external_id")
        if external_id:
            for tag in [first_record, *first_record.find_all(True)]:
                matched_attribute = next(
                    (
                        name
                        for name, value in tag.attrs.items()
                        if _SAFE_DATA_ATTRIBUTE_RE.fullmatch(str(name))
                        and _normalized(value) == _normalized(external_id)
                    ),
                    None,
                )
                if matched_attribute:
                    fields["external_id"] = {
                        "kind": "html",
                        "selector": _selector_for_tag(tag, first_record),
                        "source": "attribute",
                        "attribute": matched_attribute,
                        "transforms": ["strip"],
                    }
                    break
            if "external_id" not in fields:
                for tag in [first_record, *first_record.find_all(True)]:
                    values = onclick_navigation_values(tag)
                    if values and _normalized(values[-1]) == _normalized(external_id):
                        fields["external_id"] = {
                            "kind": "html",
                            "selector": _selector_for_tag(tag, first_record),
                            "source": "onclick_literal",
                            "transforms": ["strip"],
                        }
                        break
            if "external_id" not in fields:
                for tag in first_record.find_all("a", href=True):
                    matches = NUMERIC_PATH_SEGMENT_RE.findall(
                        urlsplit(str(tag["href"])).path
                    )
                    if matches and _normalized(matches[-1]) == _normalized(external_id):
                        fields["external_id"] = {
                            "kind": "html",
                            "selector": _selector_for_tag(tag, first_record),
                            "source": "attribute",
                            "attribute": "href",
                            "transforms": ["path_id"],
                        }
                        break

        return ExtractorRuleV1.model_validate(
            {
                "version": 1,
                "source_type": "html",
                "record_selector": record_selector,
                "fields": fields,
                "evidence_ids": ["legacy-deterministic-html"],
            }
        )
    finally:
        soup.decompose()


def build_rule_based_candidate(
    raw_data: Any,
    result: ExtractionResult,
) -> Optional[ExtractorRuleV1]:
    """Return a strict Rule V1 candidate, or ``None`` when conversion is unsafe."""
    if result.status != "success" or not result.extractor_config:
        return None
    source_type = result.extractor_config.get("source_type")
    try:
        if source_type == "json":
            return _json_candidate(result)
        if source_type == "html":
            return _html_candidate(raw_data, result)
    except (TypeError, ValueError):
        return None
    return None
