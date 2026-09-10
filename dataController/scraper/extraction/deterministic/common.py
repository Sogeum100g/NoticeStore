"""Shared constants, normalization, identity, and navigation helpers."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from dataController.scraper.navigation.html import resolve_html_navigation_url
from dataController.scraper.navigation.url_normalizer import (
    canonicalize_notice_detail_url,
)

TITLE_KEYS = (
    "title",
    "subject",
    "joboffertitle",
    "positiontitle",
    "postingtitle",
    "announcementtitle",
    "recruitmenttitle",
    "vacancytitle",
    "name",
    "headline",
    "rtnm",
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
    "companyname",
    "sdnm",
)
PUBLISHED_DATE_KEYS = (
    "publishedat",
    "publisheddate",
    "createddate",
    "createdat",
    "regdate",
    "registeredat",
    "registrationdate",
    "date",
    "게시일",
    "등록일",
    "작성일",
)
START_DATE_KEYS = (
    "startdate",
    "startdatetime",
    "applicationstartdate",
    "applystartdate",
    "접수시작일",
    "신청시작일",
    "rtacptstrtdttm",
)
END_DATE_KEYS = (
    "enddate",
    "enddatetime",
    "deadline",
    "applicationenddate",
    "applyenddate",
    "접수마감일",
    "신청마감일",
    "rtacptenddttm",
)
URL_KEYS = (
    "detailurl",
    "url",
    "href",
    "link",
    "viewurl",
    "상세url",
)
_MEDIA_CONTAINER_KEY_HINTS = (
    "media", "image", "thumbnail", "thumb", "icon", "logo",
    "cover", "photo", "picture", "avatar",
)
_IMAGE_EXTENSION_RE = re.compile(
    r"\.(?:jpg|jpeg|png|gif|webp|svg|bmp|ico)(?:\?|$)", re.IGNORECASE
)
ID_KEYS = (
    "realid",
    "jobofferid",
    "requisitionid",
    "externalid",
    "noticeid",
    "postid",
    "articleid",
    "seq",
    "id",
    "번호",
    "rtseq",
)
DATE_RE = re.compile(
    r"(?<!\d)(20\d{2}|\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*"
    r"(\d{1,2})(?:\s*일)?(?!\d|\s*(?:차|회|기))"
)
NUMERIC_METRIC_RE = re.compile(
    r"^[+-]?\d[\d,._\s]*(?:회|건|views?)?$",
    re.IGNORECASE,
)
DEADLINE_TEXT_RE = re.compile(
    r"(?:\bD\s*-\s*\d+\b|상시\s*채용|채용\s*시\s*마감|오늘\s*마감)",
    re.IGNORECASE,
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
ONCLICK_CALL_RE = re.compile(
    r"^\s*(?:return\s+)?(?P<function>[A-Za-z_$][\w.$]*)\s*"
    r"\((?P<arguments>[^)]{0,512})\)"
)
ONCLICK_ARGUMENT_RE = re.compile(
    r"^\s*(?:['\"](?P<quoted>[A-Za-z0-9_-]{1,128})['\"]|"
    r"(?P<bare>\d{1,128}))\s*$"
)
ONCLICK_NAVIGATION_HINTS = (
    "article", "board", "detail", "go", "job", "move", "notice", "open",
    "post", "recruit", "show", "view",
)
PLACEHOLDER_FRAGMENTS = {"n", "none", "void"}
KST = datetime.timezone(datetime.timedelta(hours=9))
_NUMERIC_PATH_SEGMENT_RE = re.compile(r"/(\d{2,})(?=[/?#]|$)")
HTML_EXTRACTOR_CONFIG_VERSION = 6





def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(unicodedata.normalize("NFKC", str(value)).split()).strip()






def _normalize_date(value: Any) -> Optional[str]:
    text = _normalize_text(value)
    if not text:
        return None
    if re.match(r"^20\d{2}-\d{2}-\d{2}(?:T.*)?$", text):
        return text
    if re.match(r"^20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?$", text):
        try:
            return datetime.datetime.fromisoformat(text).isoformat()
        except ValueError:
            return None
    if re.fullmatch(r"\d{10,13}", text):
        # A bare Unix epoch timestamp (seconds or milliseconds), common in
        # JSON APIs (e.g. "regDate": 1787901382718). 13 digits ~ ms since
        # epoch reach into the 2001-2286 range; 10 digits ~ seconds do the
        # same, so digit count alone reliably tells them apart.
        try:
            epoch_seconds = int(text) / 1000 if len(text) >= 12 else int(text)
            return (
                datetime.datetime.fromtimestamp(
                    epoch_seconds, tz=KST
                )
                .date()
                .isoformat()
            )
        except (ValueError, OSError, OverflowError):
            return None
    match = DATE_RE.search(text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        if year < 100:
            # Python의 strptime(%y)와 같은 경계로 최근 게시판의 단축 연도를
            # 해석한다. 예: 26.08.24 -> 2026-08-24.
            year += 2000 if year <= 68 else 1900
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



def _record_hash(notice: Dict[str, Any]) -> str:
    identity = {
        "external_id": notice.get("external_id"),
        "detail_url": canonicalize_notice_detail_url(notice.get("detail_url")),
        "title": _normalize_text(notice.get("title")).casefold(),
        "author": _normalize_text(notice.get("author")).casefold(),
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

    detail_url = canonicalize_notice_detail_url(notice.get("detail_url")) or ""
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



IMAGE_EXTENSION_RE = _IMAGE_EXTENSION_RE
MEDIA_CONTAINER_KEY_HINTS = _MEDIA_CONTAINER_KEY_HINTS
NUMERIC_PATH_SEGMENT_RE = _NUMERIC_PATH_SEGMENT_RE
append_unique_notice = _append_unique_notice
normalize_date = _normalize_date
normalize_text = _normalize_text

__all__ = [
    "AUTHOR_KEYS",
    "DEADLINE_TEXT_RE",
    "END_DATE_KEYS",
    "HTML_EXTRACTOR_CONFIG_VERSION",
    "ID_KEYS",
    "IMAGE_EXTENSION_RE",
    "MEDIA_CONTAINER_KEY_HINTS",
    "NUMERIC_METRIC_RE",
    "NUMERIC_PATH_SEGMENT_RE",
    "PUBLISHED_DATE_KEYS",
    "START_DATE_KEYS",
    "TITLE_KEYS",
    "append_unique_notice",
    "normalize_date",
    "normalize_text",
]
