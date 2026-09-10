"""Deterministic extraction from repeated HTML records."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, SoupStrainer, Tag

from dataController.scraper.extraction.deterministic.common import (
    DATE_RE,
    DEADLINE_TEXT_RE,
    HTML_EXTRACTOR_CONFIG_VERSION,
    NUMERIC_METRIC_RE,
    NUMERIC_PATH_SEGMENT_RE,
    ONCLICK_ARGUMENT_RE,
    ONCLICK_CALL_RE,
    ONCLICK_NAVIGATION_HINTS,
    PLACEHOLDER_FRAGMENTS,
    append_unique_notice,
    normalize_date,
    normalize_text,
)
from dataController.scraper.extraction.deterministic.models import ExtractionResult
from dataController.scraper.navigation.html import (
    has_navigation_metadata,
    resolve_html_navigation_url,
)
from dataController.scraper.navigation.url_normalizer import (
    canonicalize_notice_detail_url,
)

def onclick_navigation_values(element: Tag) -> List[str]:
    onclick = normalize_text(element.get("onclick"))
    match = ONCLICK_CALL_RE.match(onclick)
    if not match:
        return []

    function_name = match.group("function").casefold()
    if not any(hint in function_name for hint in ONCLICK_NAVIGATION_HINTS):
        return []

    values: List[str] = []
    for raw_argument in match.group("arguments").split(","):
        argument_match = ONCLICK_ARGUMENT_RE.match(raw_argument)
        if not argument_match:
            return []
        values.append(
            argument_match.group("quoted")
            or argument_match.group("bare")
        )
    return values


def record_external_id(record: Tag, anchor: Tag) -> Optional[str]:
    for element in (anchor, record):
        for attribute in (
            "data-value",
            "data-id",
            "data-id1",
            "data-seq",
            "data-no",
            "data-gno",
            "data-recruit-no",
            "data-article-no",
        ):
            value = normalize_text(element.get(attribute))
            compact = value.replace(",", "")
            if compact and re.match(r"^[A-Za-z0-9_-]+$", compact):
                return compact
        navigation_values = onclick_navigation_values(element)
        if navigation_values:
            return navigation_values[-1]
    href = normalize_text(anchor.get("href"))
    if href and not href.casefold().startswith(("javascript:", "#")):
        matches = NUMERIC_PATH_SEGMENT_RE.findall(urlsplit(href).path)
        if matches:
            return matches[-1]
    return None


def html_detail_url(
    base_url: str,
    anchor: Tag,
    external_id: Optional[str],
    *,
    document: Optional[BeautifulSoup] = None,
) -> Optional[str]:
    href = normalize_text(anchor.get("href"))
    parsed_href = urlsplit(href)
    is_placeholder = (
        not href
        or href in {"#", "/#"}
        or href.casefold().startswith("javascript:")
        or (
            (
                parsed_href.fragment.casefold() in PLACEHOLDER_FRAGMENTS
                or (external_id and bool(parsed_href.fragment))
            )
            and parsed_href.path in {"", "/"}
            and not parsed_href.scheme
            and not parsed_href.netloc
            and not parsed_href.query
        )
    )

    base = urlsplit(base_url)
    hostname = (base.hostname or "").casefold()
    resolved_navigation = resolve_html_navigation_url(
        base_url,
        anchor,
        document=document,
    )
    if resolved_navigation:
        return resolved_navigation
    if (
        is_placeholder
        and external_id
        and hostname.endswith("samsungcareers.com")
        and base.path.rstrip("/").casefold() == "/hr"
    ):
        return urlunsplit(
            (
                base.scheme,
                base.netloc,
                "/hr/",
                urlencode({"no": external_id}),
                "",
            )
        )
    if (
        is_placeholder
        and external_id
        and hostname == "recruit.navercorp.com"
        and base.path.rstrip("/").casefold() == "/rcrt/list.do"
    ):
        language = (parse_qs(base.query).get("lang") or ["ko"])[0]
        return urlunsplit(
            (
                base.scheme,
                base.netloc,
                "/rcrt/view.do",
                urlencode(
                    {
                        "annoId": external_id,
                        "lang": language,
                    }
                ),
                "",
            )
        )
    if (
        is_placeholder
        and external_id
        and hostname == "engineering.uos.ac.kr"
        and re.search(
            r"/korNotice/(?:allList|list)\.do$",
            base.path,
            re.IGNORECASE,
        )
    ):
        source_params = parse_qs(base.query, keep_blank_values=True)
        navigation_values = onclick_navigation_values(anchor)
        detail_params = {
            "list_id": (source_params.get("list_id") or [""])[0],
            "seq": external_id,
        }
        if len(navigation_values) >= 2:
            detail_params["sort"] = navigation_values[-2]
        for key in ("cate_id2", "cate_id", "identified"):
            if key in source_params:
                detail_params[key] = source_params[key][0]
        return urlunsplit(
            (
                base.scheme,
                base.netloc,
                re.sub(
                    r"(?:allList|list)\.do$",
                    "view.do",
                    base.path,
                    flags=re.IGNORECASE,
                ),
                urlencode(detail_params),
                "",
            )
        )
    return None if is_placeholder else _safe_detail_url(base_url, href)

def _is_navigation_anchor(anchor: Tag) -> bool:
    href = normalize_text(anchor.get("href"))
    parsed = urlsplit(href)
    is_placeholder = (
        not href
        or href in {"#", "/#"}
        or href.casefold().startswith("javascript:")
        or (
            parsed.path in {"", "/"}
            and not parsed.scheme
            and not parsed.netloc
            and not parsed.query
            and bool(parsed.fragment)
        )
    )
    if not is_placeholder:
        return True
    if onclick_navigation_values(anchor):
        return True
    return has_navigation_metadata(anchor)


def _meaningful_anchor(container: Tag) -> Optional[Tag]:
    if (
        container.name in {"a", "button"}
        or container.get("role") == "link"
    ) and _is_navigation_anchor(container):
        if len(normalize_text(container.get_text(" ", strip=True))) >= 4:
            return container

    heading = container.find(re.compile(r"^h[1-6]$"))
    if heading:
        nested = heading.select_one("a, button, [role='link']")
        if nested and _is_navigation_anchor(nested):
            return nested
        parent = heading.find_parent(["a", "button"])
        if parent and _is_navigation_anchor(parent):
            return parent

    # 제목과 기간/메타데이터가 각각 링크인 카드에서는 가장 긴 링크가
    # 제목이라는 보장이 없다. 제목 역할을 명시하는 구조를 먼저 사용한다.
    for selector in (
        "dt a[href]",
        "[class*='title'] a[href]",
        "a[class*='title'][href]",
        "p a[href]",
        "[class*='title'] button",
        "button[class*='title']",
        "[data-testid='card-title']",
        "[role='link']",
    ):
        candidate = container.select_one(selector)
        if (
            candidate
            and _is_navigation_anchor(candidate)
            and normalize_text(candidate.get_text(" ", strip=True))
        ):
            return candidate

    anchors = [
        anchor
        for anchor in container.select("a, button, [role='link']")
        if _is_navigation_anchor(anchor)
        and len(normalize_text(anchor.get_text(" ", strip=True))) >= 4
    ]
    return max(
        anchors,
        key=lambda item: len(normalize_text(item.get_text(" ", strip=True))),
        default=None,
    )


def _is_hidden_heading(element: Tag) -> bool:
    classes = {
        str(value).casefold()
        for value in (element.get("class") or [])
    }
    return bool(classes & {"blind", "hidden", "skip", "sr-only", "sr_only"})


def _record_title(record: Tag, anchor: Tag) -> str:
    heading = record.find(re.compile(r"^h[1-6]$"))
    if heading and not _is_hidden_heading(heading):
        title = normalize_text(heading.get_text(" ", strip=True))
        if title:
            return title

    for selector in (
        "dt.tit",
        "[itemprop='title']",
        "[data-testid='card-title']",
        "[class~='title']",
        "[class*='-title']",
        "[class*='_title']",
    ):
        candidate = record.select_one(selector)
        if candidate:
            direct_text = " ".join(
                str(value)
                for value in candidate.find_all(string=True, recursive=False)
            )
            title = normalize_text(
                direct_text or candidate.get_text(" ", strip=True)
            )
            if title:
                return title

    # No title-specific selector matched, so the whole anchor's text is the
    # fallback. A sibling badge inside the same anchor that's nothing but a
    # date (e.g. <span>2026.08.28</span> next to <p>title</p>) would
    # otherwise get concatenated onto the title; drop direct children whose
    # own text is only a date before falling back to the full text.
    parts = [
        child.get_text(" ", strip=True) if isinstance(child, Tag) else str(child)
        for child in anchor.children
        if not (
            isinstance(child, Tag)
            and normalize_date(child.get_text(" ", strip=True))
        )
    ]
    title = normalize_text(" ".join(parts))
    if title:
        return title
    return normalize_text(anchor.get_text(" ", strip=True))


def _css_token(tag: Tag) -> str:
    tag_id = normalize_text(tag.get("id"))
    if tag_id and re.match(r"^[A-Za-z_][\w-]*$", tag_id):
        return f"#{tag_id}"

    test_id = normalize_text(tag.get("data-testid"))
    if test_id and re.match(r"^[A-Za-z_][\w-]*$", test_id):
        return f"{tag.name}[data-testid='{test_id}']"

    classes = [
        str(value)
        for value in (tag.get("class") or [])
        if re.match(r"^[A-Za-z_][\w-]*$", str(value))
    ]
    if classes:
        return f"{tag.name}." + ".".join(classes[:2])
    return str(tag.name)


def _record_group_css(parent: Tag, child_selector: str) -> str:
    """Build a reusable selector anchored at the nearest semantic ancestor."""
    parent_token = _css_token(parent)
    if not (
        parent_token.startswith("#")
        or "[data-testid=" in parent_token
    ) and isinstance(parent.parent, Tag):
        same_token_siblings = [
            sibling
            for sibling in parent.parent.find_all(parent.name, recursive=False)
            if _css_token(sibling) == parent_token
        ]
        if len(same_token_siblings) > 1:
            same_tag_siblings = parent.parent.find_all(
                parent.name,
                recursive=False,
            )
            parent_token += (
                f":nth-of-type({same_tag_siblings.index(parent) + 1})"
            )
    if parent_token.startswith("#") or "[data-testid=" in parent_token:
        return f"{parent_token} > {child_selector}"

    path = [parent_token]
    ancestor = parent.parent
    while isinstance(ancestor, Tag) and ancestor.name != "[document]":
        token = _css_token(ancestor)
        if token.startswith("#") or "[data-testid=" in token:
            return f"{token} {child_selector}"
        path.insert(0, token)
        if token.startswith("#") or "." in token:
            break
        ancestor = ancestor.parent
    return " > ".join([*path, child_selector])


def _record_signature(record: Tag) -> Tuple[str, Tuple[str, ...]]:
    classes = tuple(
        sorted(
            str(value)
            for value in (record.get("class") or [])
            if re.match(r"^[A-Za-z_][\w-]*$", str(value))
        )
    )
    return str(record.name), classes


def _record_child_selector(
    records: List[Tag],
    sibling_records: List[Tag],
) -> str:
    """Build a selector that preserves the chosen structural subgroup."""
    tag_name = str(records[0].name)
    test_ids = {
        str(record.get("data-testid") or "").strip() for record in records
    }
    if len(test_ids) == 1:
        test_id = next(iter(test_ids))
        if test_id and re.match(r"^[A-Za-z_][\w-]*$", test_id):
            return f"{tag_name}[data-testid='{test_id}']"
    common_classes = set(_record_signature(records[0])[1])
    for record in records[1:]:
        common_classes &= set(_record_signature(record)[1])
    selector = tag_name + "".join(
        f".{class_name}" for class_name in sorted(common_classes)[:3]
    )

    selected_ids = {id(record) for record in records}
    excluded = [
        record for record in sibling_records if id(record) not in selected_ids
    ]
    selected_classes = {
        class_name
        for record in records
        for class_name in _record_signature(record)[1]
    }
    excluded_class_counts: Dict[str, int] = {}
    for record in excluded:
        for class_name in _record_signature(record)[1]:
            excluded_class_counts[class_name] = (
                excluded_class_counts.get(class_name, 0) + 1
            )
    exclusive_classes = [
        class_name
        for class_name, _count in sorted(
            excluded_class_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
        if class_name not in selected_classes
    ]
    for class_name in exclusive_classes[:3]:
        selector += f":not(.{class_name})"
    return selector


def _group_context(parent: Tag) -> str:
    values = []
    current: Optional[Tag] = parent
    for _ in range(4):
        if not isinstance(current, Tag):
            break
        values.extend(
            [
                normalize_text(current.get("id")),
                *[
                    normalize_text(value)
                    for value in (current.get("class") or [])
                ],
            ]
        )
        current = current.parent if isinstance(current.parent, Tag) else None
    return " ".join(value for value in values if value).casefold()


def _record_region_role(parent: Tag, records: List[Tag]) -> str:
    context = _group_context(parent)
    record_context = " ".join(
        " ".join(_record_signature(record)[1]) for record in records[:10]
    ).casefold()
    combined = f"{context} {record_context}"
    if re.search(r"\b(nav|menu|gnb|lnb|footer|sidebar)\b", combined):
        return "navigation"
    if re.search(r"\b(event|banner|promotion|promo|이벤트)\b", combined):
        return "event"
    if re.search(r"\b(pin|pinned|fixed|important|top-notice)\b", combined):
        return "pinned"
    return "general"


def _record_group_score(
    parent: Tag,
    records: List[Tag],
    *,
    base_url: str,
) -> int:
    """Prefer one coherent list whose links belong to the requested board."""
    base = urlsplit(base_url)
    base_path = base.path.rstrip("/").casefold()
    score = min(len(records), 30) * 2

    for record in records[:30]:
        anchor = _meaningful_anchor(record)
        if not anchor:
            continue
        detail = urlsplit(urljoin(base_url, str(anchor.get("href") or "")))
        detail_path = detail.path.rstrip("/").casefold()
        if detail.hostname == base.hostname:
            score += 2
        if base_path and (
            detail_path == base_path
            or detail_path.startswith(f"{base_path}/")
        ):
            score += 20

    context = _group_context(parent)
    if re.search(r"\b(notice|news|board|공지|게시)\b", context):
        score += 20
    if re.search(r"\b(event|banner|side|nav|menu|이벤트)\b", context):
        score -= 20
    role = _record_region_role(parent, records)
    if role == "general":
        score += 15
    elif role == "pinned":
        score -= 5
    elif role in {"event", "navigation"}:
        score -= 40
    return score


def _has_date_evidence(container: Tag) -> bool:
    """Recognize the same human-readable dates that extraction can normalize."""
    return bool(
        _date_attribute_value(container)
        or normalize_date(container.get_text(" ", strip=True))
        or DEADLINE_TEXT_RE.search(container.get_text(" ", strip=True))
    )


def _date_attribute_value(container: Tag) -> Optional[str]:
    selectors_and_attributes = (
        ("time[datetime]", "datetime"),
        ("[data-datetime]", "data-datetime"),
        ("[data-date]", "data-date"),
        ("[class*='date'][title]", "title"),
    )
    for selector, attribute in selectors_and_attributes:
        for element in container.select(selector):
            value = normalize_text(element.get(attribute))
            if normalize_date(value):
                return value
    return None


_PUBLISHED_DATE_CONTEXT_RE = re.compile(
    r"published|posted|created|reg(?:istered)?|write|board-date|"
    r"게시일|등록일|작성일",
    re.IGNORECASE,
)
_NON_PUBLISHED_DATE_CONTEXT_RE = re.compile(
    r"start|begin|from|end|deadline|due|close|period|apply|receipt|"
    r"event|schedule|calendar|신청|접수|마감|종료|기간(?!제)|개시|"
    r"행사|일정",
    re.IGNORECASE,
)


def _tag_role_context(tag: Tag) -> str:
    values = []
    current: Optional[Tag] = tag
    for _ in range(4):
        if not isinstance(current, Tag):
            break
        values.extend(
            [
                str(current.get("id") or ""),
                *[str(value) for value in (current.get("class") or [])],
                str(current.get("data-label") or ""),
                str(current.get("aria-label") or ""),
                str(current.get("title") or ""),
            ]
        )
        current = current.parent if isinstance(current.parent, Tag) else None
    return " ".join(values)


def _table_published_date_value(record: Tag) -> Optional[str]:
    cells = record.find_all(["td", "th"], recursive=False)
    table = record.find_parent("table")
    if not cells or table is None:
        return None
    header_row = next(
        (row for row in table.select("tr") if row.find("th") is not None),
        None,
    )
    if header_row is None:
        return None
    headers = header_row.find_all(["th", "td"], recursive=False)
    for index, header in enumerate(headers):
        label = normalize_text(header.get_text(" ", strip=True))
        if (
            index < len(cells)
            and _PUBLISHED_DATE_CONTEXT_RE.search(label)
            and not _NON_PUBLISHED_DATE_CONTEXT_RE.search(label)
        ):
            return (
                _date_attribute_value(cells[index])
                or normalize_text(cells[index].get_text(" ", strip=True))
            )
    return None


def _published_date_value(record: Tag) -> Optional[str]:
    table_value = _table_published_date_value(record)
    if normalize_date(table_value):
        return table_value

    record_context = _tag_role_context(record)
    record_is_non_published_region = bool(
        _NON_PUBLISHED_DATE_CONTEXT_RE.search(record_context)
    )
    date_elements = record.select(
        "time, [datetime], [data-date], [data-datetime], "
        "[class*='date'], [id*='date']"
    )
    for element in date_elements:
        context = _tag_role_context(element)
        has_explicit_published_role = bool(
            _PUBLISHED_DATE_CONTEXT_RE.search(context)
        )
        if _NON_PUBLISHED_DATE_CONTEXT_RE.search(context) or (
            record_is_non_published_region and not has_explicit_published_role
        ):
            continue
        value = (
            element.get("datetime")
            or element.get("data-datetime")
            or element.get("data-date")
            or element.get("title")
            or element.get_text(" ", strip=True)
        )
        if normalize_date(value):
            return value

    # A "게시일/등록일자 2026-08-28" label can sit in a plain span with a
    # generic class (e.g. "list") that the selector above never matches.
    # The label text itself, not the tag's class/id, is the only signal -
    # so read each element's own text and require it to name a published
    # role without also naming a conflicting one (start/deadline/etc.) in
    # the same element, which rules out wrapper tags that combine several
    # labeled dates together.
    for element in record.find_all(True):
        text = element.get_text(" ", strip=True)
        if (
            text
            and _PUBLISHED_DATE_CONTEXT_RE.search(text)
            and not _NON_PUBLISHED_DATE_CONTEXT_RE.search(text)
            and normalize_date(text)
        ):
            return text

    record_text = record.get_text(" ", strip=True)
    if (
        _NON_PUBLISHED_DATE_CONTEXT_RE.search(record_context)
        or _NON_PUBLISHED_DATE_CONTEXT_RE.search(record_text)
    ) and not _PUBLISHED_DATE_CONTEXT_RE.search(record_text):
        return None
    matches = list(DATE_RE.finditer(record_text))
    if len(matches) == 1:
        return matches[0].group(0)
    if not matches and normalize_date(record_text):
        return record_text
    return None


def _inherited_group_time(record: Tag) -> Optional[Tag]:
    """Find a nearby group header time without leaking dates across the page."""
    current = record.parent
    for _ in range(3):
        if not isinstance(current, Tag) or current.name in {"body", "html"}:
            break
        time_tag = current.find(
            "time",
            attrs={"datetime": True},
            recursive=False,
        )
        if time_tag:
            return time_tag
        current = current.parent
    return None


def _html_record_candidates(
    soup: BeautifulSoup,
    *,
    base_url: str,
) -> Tuple[str, List[Tag]]:
    table_groups: Dict[Tuple[int, Tuple[str, Tuple[str, ...]]], Tuple[Tag, List[Tag]]] = {}
    for row in soup.select("table tr"):
        anchor = _meaningful_anchor(row)
        if anchor and _has_date_evidence(row):
            parent = row.parent
            if not isinstance(parent, Tag):
                continue
            key = (id(parent), _record_signature(row))
            table_groups.setdefault(key, (parent, []))[1].append(row)
    table_candidates = []
    for parent, records in table_groups.values():
        if len(records) < 2:
            continue
        siblings = [
            child
            for child in parent.find_all("tr", recursive=False)
            if isinstance(child, Tag)
        ]
        child_selector = _record_child_selector(records, siblings)
        table_candidates.append(
            (
                _record_group_score(parent, records, base_url=base_url),
                _record_group_css(parent, child_selector),
                records,
            )
        )
    if table_candidates:
        _, selector, records = max(
            table_candidates,
            key=lambda group: (group[0], len(group[2])),
        )
        return selector, records

    for selector in ("article",):
        article_groups: Dict[
            Tuple[int, Tuple[str, Tuple[str, ...]]],
            Tuple[Tag, List[Tag]],
        ] = {}
        for item in soup.select(selector):
            if not _meaningful_anchor(item):
                continue
            local_date = _has_date_evidence(item)
            if local_date or (
                selector == "article" and _inherited_group_time(item)
            ):
                parent = item.parent
                if isinstance(parent, Tag):
                    key = (id(parent), _record_signature(item))
                    article_groups.setdefault(key, (parent, []))[1].append(item)
        article_candidates = []
        for parent, records in article_groups.values():
            if len(records) < 2:
                continue
            siblings = [
                child
                for child in parent.find_all("article", recursive=False)
                if isinstance(child, Tag)
            ]
            child_selector = _record_child_selector(records, siblings)
            article_candidates.append(
                (
                    _record_group_score(parent, records, base_url=base_url),
                    _record_group_css(parent, child_selector),
                    records,
                )
            )
        if article_candidates:
            _, record_css, records = max(
                article_candidates,
                key=lambda group: (group[0], len(group[2])),
            )
            return record_css, records

    list_groups = []
    for child_tag in ("li", "a", "ul", "ol", "dl", "div"):
        sibling_groups: Dict[
            Tuple[int, Tuple[str, Tuple[str, ...]]],
            Tuple[Tag, List[Tag]],
        ] = {}
        for item in soup.find_all(child_tag):
            parent = item.parent
            if not isinstance(parent, Tag):
                continue
            key = (id(parent), _record_signature(item))
            group = sibling_groups.setdefault(key, (parent, []))
            group[1].append(item)

        for parent, sibling_items in sibling_groups.values():
            records = []
            for item in sibling_items:
                if not _meaningful_anchor(item):
                    continue
                if not _has_date_evidence(item):
                    continue
                records.append(item)
            if len(records) < 2:
                continue
            list_groups.append(
                (
                    _record_group_score(
                        parent,
                        records,
                        base_url=base_url,
                    ),
                    _record_group_css(
                        parent,
                        _record_child_selector(
                            records,
                            [
                                child
                                for child in parent.find_all(
                                    child_tag,
                                    recursive=False,
                                )
                                if isinstance(child, Tag)
                            ],
                        ),
                    ),
                    records,
                )
            )

    if list_groups:
        _, record_css, records = max(
            list_groups,
            key=lambda group: (group[0], len(group[2])),
        )
        return record_css, records
    return "", []


def _streaming_table_candidates(html: str) -> Tuple[BeautifulSoup, List[Tag]]:
    """Retain only table rows so large SSR navigation DOMs are not materialized."""
    soup = BeautifulSoup(
        html,
        "lxml",
        parse_only=SoupStrainer("tr"),
    )
    records = []
    for row in soup.select("tr"):
        anchor = _meaningful_anchor(row)
        if anchor and _has_date_evidence(row):
            records.append(row)
    return soup, records


def _record_date_value(record: Tag) -> Any:
    published_value = _published_date_value(record)
    if published_value:
        return published_value

    inherited_time = None
    if not _NON_PUBLISHED_DATE_CONTEXT_RE.search(_tag_role_context(record)):
        inherited_time = _inherited_group_time(record)
    if inherited_time:
        return (
            inherited_time.get("datetime")
            or inherited_time.get_text(" ", strip=True)
        )
    return None


def _record_author(record: Tag, cells: List[str], title: str) -> str:
    for selector in (
        "[rel='author']",
        "span.meta strong",
        ".company",
        ".author",
        ".writer",
        ".department",
        ".dept",
        "[class*='author']",
        "[class*='writer']",
    ):
        candidate = record.select_one(selector)
        if candidate:
            text = normalize_text(candidate.get_text(" ", strip=True))
            if text and text != title:
                return text

    for cell in cells[1:]:
        if (
            cell
            and not normalize_date(cell)
            and cell != title
            and not NUMERIC_METRIC_RE.fullmatch(cell)
        ):
            return cell
    return ""


def extract_html(
    html: str,
    *,
    base_url: str,
    extractor_config: Optional[Dict[str, Any]],
) -> ExtractionResult:
    soup: Optional[BeautifulSoup] = None
    navigation_document: Optional[BeautifulSoup] = None
    try:
        if (
            extractor_config
            and extractor_config.get("source_type") == "html"
            and int(extractor_config.get("version") or 0)
            == HTML_EXTRACTOR_CONFIG_VERSION
        ):
            extractor_config = dict(extractor_config)
            record_css = extractor_config.get("record_css") or ""
            if record_css == "table tr":
                soup, records = _streaming_table_candidates(html)
            else:
                soup = BeautifulSoup(html, "lxml")
                records = soup.select(record_css) if record_css else []
        else:
            soup = BeautifulSoup(html, "lxml")
            record_css, records = _html_record_candidates(
                soup,
                base_url=base_url,
            )
            extractor_config = {
                "version": HTML_EXTRACTOR_CONFIG_VERSION,
                "source_type": "html",
                "record_css": record_css,
                "fields": {
                    "title": "record anchor/heading text",
                    "detail_url": "record anchor href",
                    "published_at": "record time/date text",
                },
            }

        if not records:
            return ExtractionResult(
                "failed", [], extractor_config, None, 0.0, None,
                "반복 HTML 레코드를 찾지 못했습니다.",
            )

        navigation_document = BeautifulSoup(
            html,
            "lxml",
            parse_only=SoupStrainer(["form", "script"]),
        )

        notices = []
        seen_identities = set()
        intermediate_records = []
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for index, record in enumerate(records):
            anchor = _meaningful_anchor(record)
            if not anchor:
                continue
            title = _record_title(record, anchor)
            if not title:
                continue
            date_value = _record_date_value(record)
            external_id = record_external_id(record, anchor)
            detail_url = html_detail_url(
                base_url,
                anchor,
                external_id,
                document=navigation_document,
            )
            detail_url = canonicalize_notice_detail_url(detail_url)
            cells = [
                normalize_text(cell.get_text(" ", strip=True))
                for cell in record.find_all(["td", "th"])
            ]
            author = _record_author(record, cells, title)
            notice = {
                "title": title,
                "author": author,
                "detail_url": detail_url,
                "external_id": external_id,
                "published_at": normalize_date(date_value),
                "url": base_url,
                "created_at": now,
                "scraped_at": now,
                "content_type": "notice",
            }
            append_unique_notice(notices, seen_identities, notice)
            intermediate_records.append(
                {
                    "record_index": index,
                    "dom_path": f"{extractor_config['record_css']}:nth-of-type({index + 1})",
                    "text_fields": cells or [
                        normalize_text(record.get_text(" ", strip=True))
                    ],
                    "links": [
                        {
                            "candidate_id": f"r{index}_a0",
                            "text": title,
                            "href": anchor.get("href"),
                            "absolute_url": detail_url,
                        }
                    ],
                }
            )

        signature = {
            "source_type": "html",
            "record_css": extractor_config.get("record_css"),
            "record_tags": [record.name for record in records[:20]],
            "cell_counts": [
                len(record.find_all(["td", "th"])) for record in records[:20]
            ],
        }
        schema_hash = hashlib.sha256(
            json.dumps(signature, sort_keys=True).encode("utf-8")
        ).hexdigest()
        intermediate = {
            "source_type": "html_repeated_records",
            "record_path": extractor_config.get("record_css"),
            "records": intermediate_records,
        }
        status = "success" if notices else "valid_empty"
        confidence = 0.96 if len(notices) >= 2 else 0.82
        return ExtractionResult(
            status,
            notices,
            extractor_config,
            schema_hash,
            confidence,
            intermediate,
        )
    finally:
        if navigation_document is not None:
            navigation_document.decompose()
        if soup is not None:
            soup.decompose()



__all__ = ["extract_html"]
