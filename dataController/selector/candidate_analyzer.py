import json
import re
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


TITLE_KEY_ALIASES = {
    "title", "subject", "article_title", "post_title", "job_title", "zz_title", "name",
}
DATE_KEY_ALIASES = {
    "date", "regdate", "reg_date", "posted", "posted_at", "created", "created_at",
    "published", "published_at", "deadline", "enddate", "end_date", "zz_end_dt", "zz_str_dt",
}
COUNT_KEY_ALIASES = {
    "count", "total", "total_count", "active_cnt", "record_count",
}
LIST_KEY_ALIASES = {
    "list", "items", "rows", "data", "result", "notices", "notice", "board",
    "posts", "post", "articles", "article", "jobs", "job",
}
AUTHOR_KEY_ALIASES = {"author", "writer", "user_name", "nickname"}
URL_KEY_ALIASES = {"url", "href", "link", "detail_url", "article_url", "post_url"}
CONTENT_KEY_ALIASES = {"content", "body", "description", "summary", "content_preview"}

NOTICE_TERMS = ("공지", "notice", "게시글", "board", "article", "채용", "recruit")
ENGLISH_MONTH_RE = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)"
)
ENGLISH_DAY_RE = r"(?:0?[1-9]|[12]\d|3[01])"
DATE_TEXT_RE = re.compile(
    r"(?:20\d{2}[.\-/]\s?\d{1,2}[.\-/]\s?\d{1,2})"
    r"|(?:\d{1,2}[./]\s?\d{1,2}\s?\([^)]+\))"
    r"|(?:\d+\s*(?:분|시간|일|주|개월|년)\s*전)"
    r"|(?:방금\s*전|오늘|어제)"
    r"|(?:\b[01]?\d|2[0-3]):[0-5]\d\b"
    rf"|(?:{ENGLISH_MONTH_RE}\.?\s*{ENGLISH_DAY_RE}(?:st|nd|rd|th)?"
    rf"(?!\d)(?:,?\s*\d{{4}})?)"
    rf"|(?:{ENGLISH_DAY_RE}(?:st|nd|rd|th)?\s+{ENGLISH_MONTH_RE}\.?"
    rf"(?:\s+\d{{4}})?)",
    re.IGNORECASE,
)
MACHINE_DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}(?:[T\s].*)?$")
MONTH_YEAR_RE = re.compile(rf"^{ENGLISH_MONTH_RE}\.?\s+20\d{{2}}$", re.IGNORECASE)
JSONP_EXTRACT_RE = re.compile(r"^[A-Za-z_$][\w$.]*\((.*)\)\s*;?\s*$", re.DOTALL)
CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
NON_KEY_RE = re.compile(r"[^a-z0-9_]+")
GENERIC_LINK_TEXTS = {
    "home", "login", "로그인", "뉴스", "가이드", "랭킹", "커뮤니티", "미디어",
    "공지사항", "업데이트", "이벤트", "전체", "공지", "점검", "이전", "다음",
    "read more", "learn more", "view more", "자세히 보기", "더보기",
}
RECORD_CONTAINER_TAGS = {"li", "article", "tr", "ul", "ol", "dl"}
RECORD_CLASS_HINTS = {
    "article", "board", "card", "entry", "item", "list", "news", "notice",
    "post", "release", "result", "row",
}


def _normalize_key(key: Any) -> str:
    text = CAMEL_BOUNDARY_RE.sub("_", str(key)).lower().replace("-", "_")
    return NON_KEY_RE.sub("", text)


def _key_category(key: Any) -> Optional[str]:
    categories = _key_categories(key)
    return next(iter(categories), None)


def _key_categories(key: Any) -> Set[str]:
    normalized = _normalize_key(key)
    categories: Set[str] = set()
    if normalized in TITLE_KEY_ALIASES:
        categories.add("title")
    if normalized in DATE_KEY_ALIASES:
        categories.add("date")
    if normalized in COUNT_KEY_ALIASES:
        categories.add("count")
    if normalized in LIST_KEY_ALIASES:
        categories.add("list")

    tokens = [token for token in normalized.split("_") if token]
    last_token = tokens[-1] if tokens else ""
    if last_token in {"title", "subject", "headline"}:
        categories.add("title")
    if last_token in {
        "date", "datetime", "timestamp", "at", "dt", "ymd",
    } and any(
        token in {
            "apply", "created", "deadline", "display", "end", "modified",
            "posted", "published", "reg", "start", "updated", "upt",
        }
        for token in tokens[:-1]
    ):
        categories.add("date")
    if last_token in {"list", "items", "rows", "results"}:
        categories.add("list")
    if last_token in {"count", "cnt"}:
        categories.add("count")
    return categories


def _record_strength(value: Dict[str, Any]) -> Tuple[bool, bool]:
    normalized_keys = {_normalize_key(key) for key in value}
    key_categories = {
        category
        for key in value
        for category in _key_categories(key)
    }
    has_title = "title" in key_categories
    has_supporting_field = bool(
        "date" in key_categories
        or normalized_keys
        & (
            AUTHOR_KEY_ALIASES
            | URL_KEY_ALIASES
            | CONTENT_KEY_ALIASES
        )
    )
    return has_title, has_supporting_field


def _walk_structured_data(value: Any) -> Tuple[Set[str], int, int, List[Dict[str, Any]], List[str]]:
    key_hits: Set[str] = set()
    max_record_count = 0
    max_title_date_pairs = 0
    sample_records: List[Dict[str, Any]] = []
    string_values: List[str] = []

    def walk(node: Any) -> None:
        nonlocal max_record_count, max_title_date_pairs, sample_records

        if isinstance(node, dict):
            normalized_keys = {_normalize_key(key) for key in node}
            for key in node:
                key_hits.update(_key_categories(key))

            if normalized_keys & TITLE_KEY_ALIASES:
                key_hits.add("title")
            if normalized_keys & DATE_KEY_ALIASES:
                key_hits.add("date")

            for child in node.values():
                walk(child)
            return

        if isinstance(node, list):
            dictionary_items = [item for item in node if isinstance(item, dict)]
            strong_records: List[Dict[str, Any]] = []
            title_date_pairs = 0
            for item in dictionary_items:
                has_title, has_supporting = _record_strength(item)
                if has_title and has_supporting:
                    strong_records.append(item)
                item_categories = {
                    category
                    for key in item
                    for category in _key_categories(key)
                }
                if {"title", "date"} <= item_categories:
                    title_date_pairs += 1

            if len(strong_records) > max_record_count:
                max_record_count = len(strong_records)
                sample_records = strong_records[:2]
            max_title_date_pairs = max(max_title_date_pairs, title_date_pairs)

            for child in node:
                walk(child)
            return

        if isinstance(node, str) and len(string_values) < 100:
            string_values.append(node)

    walk(value)
    return key_hits, max_record_count, max_title_date_pairs, sample_records, string_values


class _VisibleHTMLAnalyzer(HTMLParser):
    SKIP_TAGS = {"script", "style", "svg", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.visible_parts: List[str] = []
        self.anchor_parts: List[str] = []
        self.anchor_texts: List[str] = []
        self.heading_parts: List[str] = []
        self.heading_texts: List[str] = []
        self.machine_dates: List[str] = []
        self.record_stack: List[Dict[str, Any]] = []
        self.record_candidates: List[Dict[str, Any]] = []
        self.in_anchor = False
        self.anchor_has_href = False
        self.heading_depth = 0

    @staticmethod
    def _is_record_container(tag: str, attrs: List[Tuple[str, Optional[str]]]) -> bool:
        if tag in RECORD_CONTAINER_TAGS:
            return True
        if tag not in {"div", "section"}:
            return False

        class_value = next(
            (value for key, value in attrs if key.lower() == "class" and value),
            "",
        )
        class_tokens = {
            token
            for token in re.split(r"[^a-z0-9]+", (class_value or "").lower())
            if token
        }
        return bool(class_tokens & RECORD_CLASS_HINTS)

    def _finalize_record(self, record: Dict[str, Any]) -> None:
        text = " ".join(record["visible_parts"])
        heading_titles = [
            title
            for title in record["heading_texts"]
            if _is_meaningful_title(title) and not DATE_TEXT_RE.search(title)
        ]
        anchor_titles = [
            title for title in record["anchor_texts"] if _is_meaningful_title(title)
        ]
        titles = heading_titles or anchor_titles
        date_count = max(
            len(DATE_TEXT_RE.findall(text)),
            len(record["machine_dates"]),
        )
        if not titles:
            return
        # 날짜 헤더 하나 아래에 여러 article을 묶는 타임라인형 목록도 있다.
        # article은 HTML 자체가 독립 콘텐츠 단위를 뜻하므로, 페이지에 날짜
        # 증거가 있을 때만 상위 날짜를 상속할 수 있도록 후보로 보존한다.
        if date_count < 1 and record["tag"] != "article":
            return

        self.record_candidates.append(
            {
                "title": titles[0],
                "date_count": date_count,
                "container_tag": record["tag"],
            }
        )

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        lowered = tag.lower()
        if lowered in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if self._is_record_container(lowered, attrs):
            self.record_stack.append(
                {
                    "tag": lowered,
                    "visible_parts": [],
                    "anchor_texts": [],
                    "heading_texts": [],
                    "machine_dates": [],
                }
            )
        if lowered in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            if self.heading_depth == 0:
                self.heading_parts = []
            self.heading_depth += 1
        if lowered == "time":
            datetime_value = next(
                (
                    value
                    for key, value in attrs
                    if key.lower() == "datetime" and value
                ),
                None,
            )
            if datetime_value and MACHINE_DATE_RE.match(datetime_value):
                self.machine_dates.append(datetime_value)
                for record in self.record_stack:
                    record["machine_dates"].append(datetime_value)
        if lowered == "a":
            self.in_anchor = True
            self.anchor_parts = []
            self.anchor_has_href = any(key.lower() == "href" and bool(value) for key, value in attrs)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self.SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if lowered == "a" and self.in_anchor:
            text = " ".join(" ".join(self.anchor_parts).split())
            if self.anchor_has_href and text:
                self.anchor_texts.append(text)
                for record in self.record_stack:
                    record["anchor_texts"].append(text)
            self.in_anchor = False
            self.anchor_has_href = False
            self.anchor_parts = []
        if lowered in {"h1", "h2", "h3", "h4", "h5", "h6"} and self.heading_depth:
            self.heading_depth -= 1
            if self.heading_depth == 0:
                text = " ".join(" ".join(self.heading_parts).split())
                if text:
                    self.heading_texts.append(text)
                    for record in self.record_stack:
                        record["heading_texts"].append(text)
                self.heading_parts = []

        for index in range(len(self.record_stack) - 1, -1, -1):
            record = self.record_stack[index]
            if record["tag"] == lowered:
                self.record_stack.pop(index)
                self._finalize_record(record)
                break

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        compact = " ".join(data.split())
        if not compact:
            return
        self.visible_parts.append(compact)
        for record in self.record_stack:
            record["visible_parts"].append(compact)
        if self.in_anchor:
            self.anchor_parts.append(compact)
        if self.heading_depth:
            self.heading_parts.append(compact)


def _is_meaningful_title(text: str) -> bool:
    compact = " ".join(text.split())
    lowered = compact.lower()
    if lowered in GENERIC_LINK_TEXTS:
        return False
    if MONTH_YEAR_RE.fullmatch(compact):
        return False
    if len(compact) < 6 or len(compact) > 220:
        return False
    if compact.isdigit():
        return False
    return True


def _parse_structured_body(body_text: str, body_shape: str) -> Optional[Any]:
    compact = (body_text or "").strip()
    if not compact:
        return None

    if body_shape == "jsonp_wrapper":
        match = JSONP_EXTRACT_RE.match(compact)
        if not match:
            return None
        compact = match.group(1).strip()

    if body_shape not in {"json_object", "json_array", "jsonp_wrapper"}:
        return None

    try:
        return json.loads(compact)
    except (TypeError, ValueError):
        return None


def _semantic_sample(records: Iterable[Dict[str, Any]], fallback: str, limit: int = 400) -> str:
    records = list(records)
    if records:
        try:
            return json.dumps(records, ensure_ascii=False, separators=(",", ":"))[:limit]
        except (TypeError, ValueError):
            pass
    return " ".join((fallback or "").split())[:limit]


def analyze_candidate_body(
    body_text: str,
    *,
    body_shape: str = "",
    content_type: str = "",
) -> Dict[str, Any]:
    """응답의 실제 구조를 분석하여 목록 데이터 증거를 반환한다."""
    structured = _parse_structured_body(body_text, body_shape)
    if structured is not None:
        key_hits, record_count, title_date_pairs, records, string_values = _walk_structured_data(structured)
        combined_strings = " ".join(string_values).lower()
        has_notice_terms = any(term in combined_strings for term in NOTICE_TERMS)
        return {
            "data_key_hits": sorted(key_hits),
            "semantic_record_count": record_count,
            "title_date_pair_count": title_date_pairs,
            "has_repeated_records": record_count >= 2,
            "has_notice_terms": has_notice_terms,
            "semantic_sample": _semantic_sample(records, body_text),
            "analysis_kind": "structured",
        }

    is_html = body_shape == "html" or "html" in (content_type or "").lower()
    if is_html:
        parser = _VisibleHTMLAnalyzer()
        try:
            parser.feed(body_text or "")
            parser.close()
        except Exception:
            pass

        visible_text = " ".join(parser.visible_parts)
        meaningful_titles = [
            text
            for text in (parser.heading_texts + parser.anchor_texts)
            if _is_meaningful_title(text)
        ]
        dated_titles = list(
            dict.fromkeys(
                record["title"]
                for record in parser.record_candidates
                if record.get("title") and record.get("date_count", 0) >= 1
            )
        )
        date_count = max(
            len(DATE_TEXT_RE.findall(visible_text)),
            len(parser.machine_dates),
        )
        grouped_article_titles = list(
            dict.fromkeys(
                record["title"]
                for record in parser.record_candidates
                if record.get("title") and record.get("container_tag") == "article"
            )
        )
        # 우선순위는 레코드 내부에서 제목+날짜가 함께 확인된 증거다.
        # 그것이 부족한 경우에만, 전역 날짜 증거와 반복 article 구조를 함께
        # 요구하여 날짜 그룹형 타임라인을 목록으로 인정한다.
        if len(dated_titles) >= 2:
            localized_titles = dated_titles
        elif date_count >= 1 and len(grouped_article_titles) >= 2:
            localized_titles = grouped_article_titles
        else:
            localized_titles = dated_titles
        record_count = len(localized_titles)
        repeated = record_count >= 2
        key_hits: Set[str] = set()
        if meaningful_titles:
            key_hits.add("title")
        if date_count:
            key_hits.add("date")
        if repeated:
            key_hits.add("list")

        sample_text = " | ".join((localized_titles or meaningful_titles)[:4])
        return {
            "data_key_hits": sorted(key_hits),
            "semantic_record_count": record_count,
            "title_date_pair_count": record_count,
            "has_repeated_records": repeated,
            "has_notice_terms": any(term in visible_text.lower() for term in NOTICE_TERMS),
            "semantic_sample": (sample_text or visible_text)[:400],
            "analysis_kind": "html",
        }

    return {
        "data_key_hits": [],
        "semantic_record_count": 0,
        "title_date_pair_count": 0,
        "has_repeated_records": False,
        "has_notice_terms": False,
        "semantic_sample": " ".join((body_text or "").split())[:400],
        "analysis_kind": "other",
    }
