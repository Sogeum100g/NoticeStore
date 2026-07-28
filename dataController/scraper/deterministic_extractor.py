import datetime
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag


TITLE_KEYS = (
    "title",
    "subject",
    "name",
    "headline",
    "제목",
    "공지명",
    "게시물명",
    "pbancnm",
)
AUTHOR_KEYS = (
    "author",
    "writer",
    "department",
    "dept",
    "organization",
    "기관",
    "작성자",
    "부서",
    "담당부서",
)
DATE_KEYS = (
    "publishedat",
    "publisheddate",
    "createddate",
    "createdat",
    "regdate",
    "date",
    "게시일",
    "등록일",
    "작성일",
)
URL_KEYS = (
    "detailurl",
    "url",
    "href",
    "link",
    "viewurl",
    "상세url",
)
ID_KEYS = (
    "externalid",
    "noticeid",
    "postid",
    "articleid",
    "seq",
    "id",
    "번호",
)
DATE_RE = re.compile(
    r"(20\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})"
)
ENGLISH_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


@dataclass
class ExtractionResult:
    status: str
    notices: List[Dict[str, Any]]
    extractor_config: Optional[Dict[str, Any]]
    schema_hash: Optional[str]
    confidence: float
    intermediate: Optional[Dict[str, Any]]
    error: Optional[str] = None

    def as_processing_result(self, site_id: Optional[int] = None) -> Dict[str, Any]:
        result = {
            "status": "success" if self.status != "failed" else "error",
            "site_id": site_id,
            "notices": self.notices,
        }
        if self.error:
            result["error_msg"] = self.error
        return result


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value).casefold())


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(unicodedata.normalize("NFKC", str(value)).split()).strip()


def _matching_key(record: Dict[str, Any], aliases: Iterable[str]) -> Optional[str]:
    normalized = {_normalize_key(key): str(key) for key in record}
    for alias in aliases:
        match = normalized.get(_normalize_key(alias))
        if match is not None:
            return match
    return None


def _walk_object_arrays(
    value: Any,
    path: str = "$",
) -> List[Tuple[str, List[Dict[str, Any]]]]:
    found: List[Tuple[str, List[Dict[str, Any]]]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if isinstance(child, list) and all(
                isinstance(item, dict) for item in child
            ):
                found.append((child_path, child))
            found.extend(_walk_object_arrays(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value[:20]):
            found.extend(_walk_object_arrays(child, f"{path}[{index}]"))
    return found


def _choose_json_records(
    value: Any,
) -> Optional[Tuple[str, List[Dict[str, Any]], Dict[str, str]]]:
    candidates = _walk_object_arrays(value)
    best = None
    best_score = -1
    for path, records in candidates:
        sample = records[:20]
        if not sample:
            continue
        title_key = next(
            (_matching_key(record, TITLE_KEYS) for record in sample),
            None,
        )
        if not title_key:
            continue
        keys = {
            "title": title_key,
            "author": _matching_key(sample[0], AUTHOR_KEYS),
            "published_at": _matching_key(sample[0], DATE_KEYS),
            "detail_url": _matching_key(sample[0], URL_KEYS),
            "external_id": _matching_key(sample[0], ID_KEYS),
        }
        title_presence = sum(
            bool(_normalize_text(record.get(title_key))) for record in sample
        )
        consistent_keys = len(set.intersection(*(set(r.keys()) for r in sample)))
        score = title_presence * 10 + min(len(records), 20) + consistent_keys
        if score > best_score:
            best = (path, records, {k: v for k, v in keys.items() if v})
            best_score = score
    return best


def _records_at_path(value: Any, path: str) -> Optional[List[Dict[str, Any]]]:
    if not path.startswith("$"):
        return None
    current = value
    for key, index in re.findall(r"\.([^.\[]+)|\[(\d+)\]", path[1:]):
        if key:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        else:
            if not isinstance(current, list) or int(index) >= len(current):
                return None
            current = current[int(index)]
    if not isinstance(current, list) or not all(
        isinstance(item, dict) for item in current
    ):
        return None
    return current


def _safe_detail_url(base_url: str, candidate: Any) -> Optional[str]:
    text = _normalize_text(candidate)
    if not text:
        return None
    absolute = urljoin(base_url, text)
    parsed = urlsplit(absolute)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return absolute


def _normalize_date(value: Any) -> Optional[str]:
    text = _normalize_text(value)
    if not text:
        return None
    if re.match(r"^20\d{2}-\d{2}-\d{2}(?:T.*)?$", text):
        return text
    match = DATE_RE.search(text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        try:
            return datetime.date(year, month, day).isoformat()
        except ValueError:
            return None
    english_patterns = (
        re.search(
            r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b",
            text,
            re.IGNORECASE,
        ),
        re.search(
            r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(20\d{2})\b",
            text,
            re.IGNORECASE,
        ),
    )
    for index, english_match in enumerate(english_patterns):
        if not english_match:
            continue
        if index == 0:
            month_name, day, year = english_match.groups()
        else:
            day, month_name, year = english_match.groups()
        month = ENGLISH_MONTHS.get(month_name.casefold().rstrip("."))
        if not month:
            continue
        try:
            return datetime.date(int(year), month, int(day)).isoformat()
        except ValueError:
            return None
    return None


def parse_json_or_jsonp(text: str) -> Any:
    stripped = str(text or "").strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as original_error:
        match = re.match(
            r"^[A-Za-z_$][\w.$]*\s*\(\s*(.*)\s*\)\s*;?\s*$",
            stripped,
            re.DOTALL,
        )
        if not match:
            raise original_error
        return json.loads(match.group(1))


def _record_hash(notice: Dict[str, Any]) -> str:
    identity = {
        "external_id": notice.get("external_id"),
        "detail_url": notice.get("detail_url"),
        "title": _normalize_text(notice.get("title")).casefold(),
        "published_at": notice.get("published_at"),
    }
    return hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _notice_identity(notice: Dict[str, Any]) -> Tuple[str, ...]:
    external_id = _normalize_text(notice.get("external_id")).casefold()
    if external_id:
        return ("external_id", external_id)

    detail_url = _normalize_text(notice.get("detail_url"))
    if detail_url:
        return ("detail_url", detail_url)

    return (
        "content",
        _normalize_text(notice.get("title")).casefold(),
        _normalize_text(notice.get("published_at")),
    )


def _append_unique_notice(
    notices: List[Dict[str, Any]],
    seen_identities: set,
    notice: Dict[str, Any],
) -> bool:
    identity = _notice_identity(notice)
    if identity in seen_identities:
        return False
    seen_identities.add(identity)
    notice["record_hash"] = _record_hash(notice)
    notices.append(notice)
    return True


def _json_intermediate(
    records_path: str,
    records: List[Dict[str, Any]],
    fields: Dict[str, str],
) -> Dict[str, Any]:
    return {
        "source_type": "json_records",
        "record_path": records_path,
        "records": [
            {
                "record_index": index,
                "json_path": f"{records_path}[{index}]",
                "fields": {
                    output_name: {
                        "json_path": f"{records_path}[{index}].{source_key}",
                        "value": record.get(source_key),
                    }
                    for output_name, source_key in fields.items()
                },
            }
            for index, record in enumerate(records)
        ],
    }


def _extract_json(
    value: Any,
    *,
    base_url: str,
    extractor_config: Optional[Dict[str, Any]],
) -> ExtractionResult:
    if extractor_config and extractor_config.get("source_type") == "json":
        records_path = extractor_config.get("records_path")
        fields = extractor_config.get("fields") or {}
        records = _records_at_path(value, records_path)
        if records is None:
            return ExtractionResult(
                "failed", [], extractor_config, None, 0.0, None,
                "저장된 JSON records_path가 현재 원문에 없습니다.",
            )
    else:
        chosen = _choose_json_records(value)
        if not chosen:
            return ExtractionResult(
                "failed", [], None, None, 0.0, None,
                "제목 필드를 가진 반복 JSON 레코드를 찾지 못했습니다.",
            )
        records_path, records, fields = chosen
        extractor_config = {
            "version": 1,
            "source_type": "json",
            "records_path": records_path,
            "fields": fields,
        }

    notices: List[Dict[str, Any]] = []
    seen_identities = set()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for record in records:
        title = _normalize_text(record.get(fields.get("title")))
        if not title:
            continue
        notice = {
            "title": title,
            "author": _normalize_text(record.get(fields.get("author"))),
            "detail_url": _safe_detail_url(
                base_url,
                record.get(fields.get("detail_url")),
            ),
            "external_id": _normalize_text(
                record.get(fields.get("external_id"))
            ) or None,
            "published_at": _normalize_date(
                record.get(fields.get("published_at"))
            ),
            "url": base_url,
            "created_at": now,
            "scraped_at": now,
            "content_type": "notice",
        }
        _append_unique_notice(notices, seen_identities, notice)

    intermediate = _json_intermediate(records_path, records, fields)
    signature = {
        "source_type": "json",
        "records_path": records_path,
        "keys": sorted({key for record in records[:20] for key in record}),
    }
    schema_hash = hashlib.sha256(
        json.dumps(signature, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    status = "success" if notices else "valid_empty"
    confidence = 0.98 if len(notices) >= 2 else 0.85
    return ExtractionResult(
        status,
        notices,
        extractor_config,
        schema_hash,
        confidence,
        intermediate,
    )


def _meaningful_anchor(container: Tag) -> Optional[Tag]:
    heading = container.find(re.compile(r"^h[1-6]$"))
    if heading:
        nested = heading.find("a", href=True)
        if nested:
            return nested
        parent = heading.find_parent("a", href=True)
        if parent:
            return parent
    anchors = [
        anchor
        for anchor in container.find_all("a", href=True)
        if len(_normalize_text(anchor.get_text(" ", strip=True))) >= 4
    ]
    return max(
        anchors,
        key=lambda item: len(_normalize_text(item.get_text(" ", strip=True))),
        default=None,
    )


def _html_record_candidates(soup: BeautifulSoup) -> Tuple[str, List[Tag]]:
    table_rows = []
    for row in soup.select("table tr"):
        anchor = _meaningful_anchor(row)
        if anchor and DATE_RE.search(row.get_text(" ", strip=True)):
            table_rows.append(row)
    if len(table_rows) >= 2:
        return "table tr", table_rows

    for selector in ("article", "li"):
        containers = []
        global_has_date = bool(
            soup.find("time", attrs={"datetime": True})
            or DATE_RE.search(soup.get_text(" ", strip=True))
        )
        for item in soup.select(selector):
            if not _meaningful_anchor(item):
                continue
            local_date = (
                item.find("time", attrs={"datetime": True})
                or DATE_RE.search(item.get_text(" ", strip=True))
            )
            if local_date or (selector == "article" and global_has_date):
                containers.append(item)
        if len(containers) >= 2:
            return selector, containers
    return "", []


def _record_date_value(record: Tag) -> Any:
    time_tag = record.find("time")
    if time_tag:
        return time_tag.get("datetime") or time_tag.get_text(" ", strip=True)

    local_text = record.get_text(" ", strip=True)
    if _normalize_date(local_text):
        return local_text

    previous_time = record.find_previous("time")
    if previous_time:
        return (
            previous_time.get("datetime")
            or previous_time.get_text(" ", strip=True)
        )
    return None


def _record_author(record: Tag, cells: List[str], title: str) -> str:
    for selector in (
        "[rel='author']",
        ".author",
        ".writer",
        ".department",
        ".dept",
        "[class*='author']",
        "[class*='writer']",
    ):
        candidate = record.select_one(selector)
        if candidate:
            text = _normalize_text(candidate.get_text(" ", strip=True))
            if text and text != title:
                return text

    for cell in cells[1:]:
        if cell and not _normalize_date(cell) and cell != title:
            return cell
    return ""


def _extract_html(
    html: str,
    *,
    base_url: str,
    extractor_config: Optional[Dict[str, Any]],
) -> ExtractionResult:
    soup = BeautifulSoup(html, "lxml")
    try:
        if extractor_config and extractor_config.get("source_type") == "html":
            record_css = extractor_config.get("record_css") or ""
            records = soup.select(record_css) if record_css else []
        else:
            record_css, records = _html_record_candidates(soup)
            extractor_config = {
                "version": 1,
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

        notices = []
        seen_identities = set()
        intermediate_records = []
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for index, record in enumerate(records):
            anchor = _meaningful_anchor(record)
            if not anchor:
                continue
            heading = record.find(re.compile(r"^h[1-6]$"))
            title = _normalize_text(
                heading.get_text(" ", strip=True)
                if heading
                else anchor.get_text(" ", strip=True)
            )
            if not title:
                continue
            date_value = _record_date_value(record)
            detail_url = _safe_detail_url(base_url, anchor.get("href"))
            cells = [
                _normalize_text(cell.get_text(" ", strip=True))
                for cell in record.find_all(["td", "th"])
            ]
            author = _record_author(record, cells, title)
            notice = {
                "title": title,
                "author": author,
                "detail_url": detail_url,
                "external_id": None,
                "published_at": _normalize_date(date_value),
                "url": base_url,
                "created_at": now,
                "scraped_at": now,
                "content_type": "notice",
            }
            _append_unique_notice(notices, seen_identities, notice)
            intermediate_records.append(
                {
                    "record_index": index,
                    "dom_path": f"{extractor_config['record_css']}:nth-of-type({index + 1})",
                    "text_fields": cells or [
                        _normalize_text(record.get_text(" ", strip=True))
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
        soup.decompose()


def extract_notices_deterministically(
    raw_data: Any,
    *,
    content_type: str,
    base_url: str,
    extractor_config: Optional[Dict[str, Any]] = None,
) -> ExtractionResult:
    try:
        if isinstance(raw_data, (dict, list)):
            return _extract_json(
                raw_data,
                base_url=base_url,
                extractor_config=extractor_config,
            )

        text = str(raw_data or "")
        looks_json_like = text.lstrip().startswith(("{", "["))
        looks_jsonp_like = bool(
            re.match(
                r"^[A-Za-z_$][\w.$]*\s*\(",
                text.lstrip(),
            )
        )
        if (
            "json" in content_type
            or "javascript" in content_type
            or looks_json_like
            or looks_jsonp_like
        ):
            return _extract_json(
                parse_json_or_jsonp(text),
                base_url=base_url,
                extractor_config=extractor_config,
            )
        return _extract_html(
            text,
            base_url=base_url,
            extractor_config=extractor_config,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return ExtractionResult(
            "failed",
            [],
            extractor_config,
            None,
            0.0,
            None,
            str(exc),
        )
