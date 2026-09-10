"""Deterministic extraction from decoded JSON records."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from dataController.scraper.extraction.deterministic.common import (
    AUTHOR_KEYS,
    END_DATE_KEYS,
    ID_KEYS,
    IMAGE_EXTENSION_RE,
    MEDIA_CONTAINER_KEY_HINTS,
    PUBLISHED_DATE_KEYS,
    START_DATE_KEYS,
    TITLE_KEYS,
    URL_KEYS,
    append_unique_notice,
    normalize_date,
    normalize_text,
)
from dataController.scraper.extraction.deterministic.models import ExtractionResult
from dataController.scraper.navigation.url_normalizer import (
    canonicalize_notice_detail_url,
)

def _normalize_key(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value).casefold())

def date_key_role(key: Any) -> str:
    normalized = _normalize_key(key)
    if any(
        token in normalized
        for token in (
            "start", "begin", "from", "시작", "개시", "접수시작", "신청시작",
        )
    ):
        return "application_start_at"
    if any(
        token in normalized
        for token in (
            "end", "deadline", "due", "close", "마감", "종료", "접수마감",
            "신청마감",
        )
    ):
        return "application_end_at"
    return "published_at"

def matching_key(record: Dict[str, Any], aliases: Iterable[str]) -> Optional[str]:
    normalized = {_normalize_key(key): str(key) for key in record}
    for alias in aliases:
        match = normalized.get(_normalize_key(alias))
        if match is not None:
            return match

    role_suffixes: Tuple[str, ...] = ()
    if aliases is TITLE_KEYS:
        role_suffixes = ("title", "subject", "headline")
    elif aliases is PUBLISHED_DATE_KEYS:
        role_suffixes = (
            "date", "datetime", "timestamp", "publishedat", "createdat",
            "updatedat", "postedat",
        )
    elif aliases is START_DATE_KEYS:
        role_suffixes = ("startdate", "startdatetime", "begindate")
    elif aliases is END_DATE_KEYS:
        role_suffixes = ("enddate", "enddatetime", "deadline", "duedate")
    elif aliases is URL_KEYS:
        role_suffixes = ("url", "href", "link")
    elif aliases is ID_KEYS:
        role_suffixes = ("id", "seq", "no")

    if role_suffixes:
        for key in record:
            normalized_key = _normalize_key(key)
            if (
                normalized_key.endswith(role_suffixes)
                and (
                    aliases is not PUBLISHED_DATE_KEYS
                    or date_key_role(key) == "published_at"
                )
            ):
                return str(key)
    return None


def matching_top_level_url_key(record: Dict[str, Any]) -> Optional[str]:
    """``matching_key(record, URL_KEYS)``, but rejecting a match whose own
    key name or value marks it as image/media content (e.g. a top-level
    "thumbnailUrl" field) rather than a real navigation link - the same
    distinction ``matching_nested_url_path`` already makes for nested
    fields.
    """
    key = matching_key(record, URL_KEYS)
    if key is None:
        return None
    if any(hint in _normalize_key(key) for hint in MEDIA_CONTAINER_KEY_HINTS):
        return None
    value = record.get(key)
    if isinstance(value, str) and IMAGE_EXTENSION_RE.search(value):
        return None
    return key


def matching_nested_url_path(
    record: Dict[str, Any],
    *,
    max_depth: int = 3,
) -> Optional[str]:
    """Find a navigation URL nested inside a record's sub-objects.

    ``matching_key`` only looks at a record's own top-level keys. A record
    can carry several differently-named URL fields at once (thumbnail,
    author avatar, the actual detail link), so this walks into nested
    objects while skipping containers whose own key name suggests
    image/media content and rejecting values that look like image URLs -
    matching the field name and the value shape a real "go to detail"
    link should have, not just any nested ``url`` key.
    """

    def walk(node: Any, path: List[str], depth: int) -> Optional[str]:
        if not isinstance(node, dict) or depth > max_depth:
            return None
        direct = matching_key(node, URL_KEYS)
        if direct:
            value = node.get(direct)
            if (
                isinstance(value, str)
                and value.strip()
                and not IMAGE_EXTENSION_RE.search(value)
            ):
                return ".".join([*path, direct])
        for key, child in node.items():
            if any(
                hint in _normalize_key(key) for hint in MEDIA_CONTAINER_KEY_HINTS
            ):
                continue
            found = walk(child, [*path, str(key)], depth + 1)
            if found:
                return found
        return None

    return walk(record, [], 0)


def field_value(record: Dict[str, Any], field_key: Optional[str]) -> Any:
    """Read ``field_key`` off ``record``, following dotted nested paths."""
    if not field_key:
        return None
    if "." not in field_key:
        return record.get(field_key)
    current: Any = record
    for segment in field_key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


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


def choose_json_records(
    value: Any,
) -> Optional[
    Tuple[
        str,
        List[Dict[str, Any]],
        Dict[str, str],
        Dict[str, str],
    ]
]:
    candidates = _walk_object_arrays(value)
    best = None
    best_score = -1
    for path, records in candidates:
        sample = records[:20]
        if not sample:
            continue
        title_key = next(
            (matching_key(record, TITLE_KEYS) for record in sample),
            None,
        )
        if not title_key:
            continue
        published_key = matching_key(sample[0], PUBLISHED_DATE_KEYS)
        start_key = matching_key(sample[0], START_DATE_KEYS)
        end_key = matching_key(sample[0], END_DATE_KEYS)
        keys = {
            "title": title_key,
            "author": matching_key(sample[0], AUTHOR_KEYS),
            "published_at": published_key,
            "detail_url": (
                matching_top_level_url_key(sample[0])
                or matching_nested_url_path(sample[0])
            ),
            "external_id": matching_key(sample[0], ID_KEYS),
        }
        title_presence = sum(
            bool(normalize_text(record.get(title_key))) for record in sample
        )
        consistent_keys = len(set.intersection(*(set(r.keys()) for r in sample)))
        score = title_presence * 10 + min(len(records), 20) + consistent_keys
        if score > best_score:
            best = (
                path,
                records,
                {k: v for k, v in keys.items() if v},
                {
                    key: value
                    for key, value in {
                        "published_at": published_key,
                        "application_start_at": start_key,
                        "application_end_at": end_key,
                    }.items()
                    if value
                },
            )
            best_score = score
    return best


def records_at_path(value: Any, path: str) -> Optional[List[Dict[str, Any]]]:
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


def safe_detail_url(base_url: str, candidate: Any) -> Optional[str]:
    text = normalize_text(candidate)
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
                        "value": field_value(record, source_key),
                    }
                    for output_name, source_key in fields.items()
                },
            }
            for index, record in enumerate(records)
        ],
    }


def extract_json(
    value: Any,
    *,
    base_url: str,
    extractor_config: Optional[Dict[str, Any]],
) -> ExtractionResult:
    if extractor_config and extractor_config.get("source_type") == "json":
        extractor_config = dict(extractor_config)
        records_path = extractor_config.get("records_path")
        fields = dict(extractor_config.get("fields") or {})
        stored_published_key = fields.get("published_at")
        if (
            stored_published_key
            and date_key_role(stored_published_key) != "published_at"
        ):
            fields.pop("published_at", None)
        records = records_at_path(value, records_path)
        if records is None:
            return ExtractionResult(
                "failed", [], extractor_config, None, 0.0, None,
                "저장된 JSON records_path가 현재 원문에 없습니다.",
            )
        date_roles = dict(extractor_config.get("date_roles") or {})
        if records:
            published_key = matching_key(records[0], PUBLISHED_DATE_KEYS)
            start_key = matching_key(records[0], START_DATE_KEYS)
            end_key = matching_key(records[0], END_DATE_KEYS)
            date_roles = {
                key: value
                for key, value in {
                    "published_at": published_key,
                    "application_start_at": start_key,
                    "application_end_at": end_key,
                }.items()
                if value
            }
            if published_key:
                fields["published_at"] = published_key
        extractor_config["version"] = 2
        extractor_config["fields"] = fields
        extractor_config["date_roles"] = date_roles
    else:
        chosen = choose_json_records(value)
        if not chosen:
            return ExtractionResult(
                "failed", [], None, None, 0.0, None,
                "제목 필드를 가진 반복 JSON 레코드를 찾지 못했습니다.",
            )
        records_path, records, fields, date_roles = chosen
        extractor_config = {
            "version": 2,
            "source_type": "json",
            "records_path": records_path,
            "fields": fields,
            "date_roles": date_roles,
        }

    notices: List[Dict[str, Any]] = []
    seen_identities = set()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for record in records:
        title = normalize_text(field_value(record, fields.get("title")))
        if not title:
            continue
        external_id = normalize_text(
            field_value(record, fields.get("external_id"))
        ) or None
        detail_url = safe_detail_url(
            base_url,
            field_value(record, fields.get("detail_url")),
        )
        parsed_base = urlsplit(base_url)
        if (
            not detail_url
            and external_id
            and (parsed_base.hostname or "").casefold()
            == "careers.kakao.com"
            and parsed_base.path.rstrip("/").casefold() == "/jobs"
        ):
            detail_url = urlunsplit(
                (
                    parsed_base.scheme,
                    parsed_base.netloc,
                    f"/jobs/{external_id}",
                    parsed_base.query,
                    "",
                )
            )
        if (
            not detail_url
            and external_id
            and (parsed_base.hostname or "").casefold()
            == "www.hanwhain.com"
            and parsed_base.path.rstrip("/").casefold()
            == "/portal/apply/recruit"
        ):
            detail_url = urlunsplit(
                (
                    parsed_base.scheme,
                    parsed_base.netloc,
                    "/portal/apply/recruit/detail",
                    urlencode({"rtSeq": external_id}),
                    "",
                )
            )

        detail_url = canonicalize_notice_detail_url(detail_url)

        notice = {
            "title": title,
            "author": normalize_text(field_value(record, fields.get("author"))),
            "detail_url": detail_url,
            "external_id": external_id,
            "published_at": normalize_date(
                field_value(record, fields.get("published_at"))
            ),
            "url": base_url,
            "created_at": now,
            "scraped_at": now,
            "content_type": "notice",
        }
        append_unique_notice(notices, seen_identities, notice)

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



__all__ = ["extract_json"]
