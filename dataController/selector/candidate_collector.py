import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright

from dataController.security.url_safety import UnsafeUrlError, validate_public_url

try:
    from .candidate_analyzer import analyze_candidate_body
except ImportError:  # pragma: no cover
    from dataController.selector.candidate_analyzer import analyze_candidate_body

logger = logging.getLogger(__name__)

CURRENT_DIR = Path(__file__).resolve().parent
SCRAPE_DIR = CURRENT_DIR.parent
TAG_PATH = SCRAPE_DIR / "tag.json"

ABORT_RESOURCE_TYPES = {"image", "stylesheet", "media", "font"}
SKIP_RESOURCE_TYPES = {"image", "stylesheet", "media", "font", "websocket"}
TRASH_EXTENSIONS = (
    ".js", ".mjs", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg",
    ".ico", ".woff", ".woff2", ".map", ".mp4", ".mp3", ".webm"
)
LEGACY_DATA_ENDPOINT_HINTS = (".fo", ".do", ".data", ".action", ".ajax")
TEXTUAL_CONTENT_TYPE_HINTS = (
    "text/html",
    "application/json",
    "text/json",
    "application/xml",
    "text/xml",
    "text/plain",
    "application/javascript",
    "text/javascript",
    "application/x-javascript",
    "text/x-javascript",
    "application/graphql-response+json",
    "javasciprt",
)
DROP_REQUEST_HEADERS = {
    "cookie", "content-length", "content-encoding", "host", "connection",
    "accept-encoding", "cache-control"
}
MAX_TEXT_READ_BYTES = 700_000
MIN_TEXTUAL_BODY_BYTES = 80
MAX_CANDIDATES = 20
KEYWORD_HINTS = (
    "공지", "notice", "조회수", "첨부파일", "게시", "board", "title", "subject", "list"
)
DATA_KEY_HINTS = (
    "title", "subject", "content", "writer", "regdate", "date", "posted", "list",
    "items", "rows", "total_count", "count", "notice", "board", "zz_title", "zz_end_dt",
    "zz_jo_num", "article", "post", "job", "recruit", "apply", "deadline"
)
JSONP_CALLBACK_HEAD_RE = re.compile(r"^[A-Za-z_$][\w$.]*\s*\(")
JSONP_EXTRACT_RE = re.compile(r"^[A-Za-z_$][\w$.]*\((.*)\)\s*;?\s*$", re.DOTALL)


def _load_tag_data() -> Dict[str, Any]:
    if TAG_PATH.exists():
        with open(TAG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _sanitize_headers(headers: Dict[str, str]) -> Dict[str, str]:
    cleaned: Dict[str, str] = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower in DROP_REQUEST_HEADERS:
            continue
        if lower.startswith("sec-ch-") or lower.startswith("sec-fetch-"):
            continue
        cleaned[key] = value
    return cleaned


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.replace("\r", " ").replace("\n", " ").split())


def _parse_body_payload(raw_payload: Optional[str]) -> Tuple[Optional[Dict[str, Any]], str]:
    if not raw_payload:
        return None, "query_only"

    try:
        parsed_json = json.loads(raw_payload)
        if isinstance(parsed_json, dict):
            return parsed_json, "json"
    except json.JSONDecodeError:
        pass

    try:
        body_params = parse_qs(raw_payload, keep_blank_values=True)
        if body_params:
            return {k: v[0] if len(v) == 1 else v for k, v in body_params.items()}, "form"
    except Exception:
        pass

    return {"_raw": raw_payload[:1000]}, "raw"


def _build_dedupe_key(method: str, url: str, query_params: Dict[str, Any], body_payload: Optional[Dict[str, Any]]) -> str:
    return json.dumps(
        {
            "method": method,
            "url": url,
            "query": query_params,
            "body": body_payload or {},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _looks_textual(content_type: str, resource_type: str, url: str) -> bool:
    if resource_type not in {"document", "fetch", "xhr", "script"}:
        return False
    lowered_url = url.lower()
    if any(lowered_url.endswith(ext) for ext in LEGACY_DATA_ENDPOINT_HINTS):
        return True
    if "callback=" in lowered_url:
        return True
    if not content_type:
        return True
    return any(hint in content_type for hint in TEXTUAL_CONTENT_TYPE_HINTS)


def _extract_jsonp_payload(text: str) -> Optional[Any]:
    if not text:
        return None

    compact = text.strip()
    match = JSONP_EXTRACT_RE.match(compact)
    if not match:
        return None

    inner = match.group(1).strip()
    try:
        return json.loads(inner)
    except Exception:
        return None


def _detect_body_shape(body_text: str) -> str:
    if not body_text:
        return "empty"

    head = body_text[:120].strip()
    if head.startswith("{"):
        return "json_object"
    if head.startswith("["):
        return "json_array"
    if head.startswith("<"):
        return "html"
    if JSONP_CALLBACK_HEAD_RE.match(head):
        return "jsonp_wrapper"
    if "var " in head or "window." in head:
        return "javascript_bridge"
    return "textual_other"


def _find_data_key_hits(body_text: str, limit: int = 10) -> List[str]:
    lowered = (body_text or "").lower()
    hits: List[str] = []
    for key in DATA_KEY_HINTS:
        if key in lowered:
            hits.append(key)
        if len(hits) >= limit:
            break
    return hits


def _extract_informative_sample(
    body_text: str,
    *,
    limit: int = 400,
    parsed_jsonp: Optional[Any] = None,
) -> str:
    if parsed_jsonp is not None:
        try:
            payload_for_sample: Any = parsed_jsonp
            if isinstance(parsed_jsonp, list):
                payload_for_sample = parsed_jsonp[:2]
            compact_json = json.dumps(payload_for_sample, ensure_ascii=False, separators=(",", ":"))
            return compact_json[:limit]
        except Exception:
            pass

    if not body_text:
        return ""

    compact = _normalize_whitespace(body_text)
    if not compact:
        return ""

    lower_compact = compact.lower()
    best_idx: Optional[int] = None
    for keyword in KEYWORD_HINTS + DATA_KEY_HINTS:
        idx = lower_compact.find(keyword.lower())
        if idx != -1:
            best_idx = idx
            break

    if best_idx is None:
        return compact[:limit]

    start = max(0, best_idx - 120)
    return compact[start:start + limit]


def _classify_source_kind(
    *,
    method: str,
    resource_type: str,
    content_type: str,
    url: str,
    has_body_payload: bool,
    body_shape: str,
    has_callback_param: bool,
    data_key_hits: List[str],
) -> str:
    lowered_url = url.lower()
    if "graphql" in lowered_url:
        return "graphql"
    if has_callback_param or body_shape == "jsonp_wrapper":
        return "jsonp_javascript"
    if resource_type == "script" and data_key_hits:
        return "script_data"
    # 브라우저가 navigation 응답의 Content-Type을 누락하거나 다르게
    # 보고하더라도 실제 본문이 HTML이면 document 후보로 분류한다.
    if resource_type == "document" and (
        "text/html" in content_type or body_shape == "html"
    ):
        return "document_html"
    if body_shape == "javascript_bridge" and data_key_hits:
        return "bridge_javascript"
    if method == "POST" and has_body_payload:
        if "json" in content_type:
            return "post_json"
        return "form_post"
    if resource_type in {"xhr", "fetch"} and "json" in content_type:
        return "xhr_json"
    if resource_type in {"xhr", "fetch"} and "html" in content_type:
        return "xhr_html"
    if resource_type in {"xhr", "fetch"}:
        return "xhr_other"
    if resource_type == "script":
        return "script_other"
    return f"{resource_type}_other"


def _should_keep_candidate(
    *,
    url: str,
    body_text: str,
    body_shape: str,
    has_callback_param: bool,
    data_key_hits: List[str],
) -> bool:
    if not body_text:
        return True

    lowered_url = url.lower()
    if body_shape in {"json_object", "json_array", "html", "jsonp_wrapper"}:
        return True
    if has_callback_param:
        return True
    if any(lowered_url.endswith(ext) for ext in LEGACY_DATA_ENDPOINT_HINTS) and data_key_hits:
        return True
    if data_key_hits:
        return True
    return False


async def collect_candidates(
    target_url: str,
    *,
    goto_timeout_ms: int = 15000,
    min_observe_sec: float = 2.0,
    max_observe_sec: float = 6.0,
    quiet_window_sec: float = 1.5,
    enough_candidates: int = 4,
) -> List[Dict[str, Any]]:
    """
    Playwright-first shallow discovery collector.
    - 브라우저는 유지하되 전체 렌더 완료를 기다리지 않습니다.
    - document / fetch / xhr / POST / JSONP / script-data 후보를 폭넓게 수집합니다.
    - 시각적 리소스는 route abort로 실제 네트워크 비용도 줄입니다.
    """
    try:
        validated_target = await asyncio.to_thread(validate_public_url, target_url)
        target_url = validated_target.url
    except UnsafeUrlError as exc:
        logger.warning("후보 수집 전 URL 보안 검증 실패: %s", exc)
        return []

    tag_data = _load_tag_data()
    global_trash_keywords = tag_data.get("GLOBAL_TRASH_KEYWORDS", [])

    candidates: List[Dict[str, Any]] = []
    seen_keys = set()
    api_index = 1
    last_candidate_at = time.monotonic()

    async with async_playwright() as p:
        browser = None
        try:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
        except Exception:
            logger.error("❌ 브라우저 초기화 실패", exc_info=True)
            if browser:
                await browser.close()
            return []

        async def route_handler(route):
            resource_type = route.request.resource_type
            if resource_type in ABORT_RESOURCE_TYPES:
                await route.abort()
                return
            try:
                await asyncio.to_thread(validate_public_url, route.request.url)
            except UnsafeUrlError:
                logger.warning("안전하지 않은 브라우저 요청 차단: %s", route.request.url)
                await route.abort()
                return
            await route.continue_()

        await page.route("**/*", route_handler)

        async def capture_response(response):
            nonlocal api_index, last_candidate_at

            if len(candidates) >= MAX_CANDIDATES:
                return

            request = response.request
            method = request.method.upper()
            resource_type = request.resource_type

            try:
                await asyncio.to_thread(validate_public_url, request.url)
            except UnsafeUrlError:
                logger.warning("안전하지 않은 API 후보 제외: %s", request.url)
                return

            if method == "OPTIONS":
                return
            if resource_type in SKIP_RESOURCE_TYPES:
                return

            parsed_req_url = urlparse(request.url)
            req_path = parsed_req_url.path.lower()
            if req_path.endswith(TRASH_EXTENSIONS):
                return
            if any(trash in request.url for trash in global_trash_keywords):
                return

            content_type = response.headers.get("content-type", "").lower()
            if not _looks_textual(content_type, resource_type, request.url):
                return
            if response.status < 200 or response.status >= 400:
                return

            query_params_raw = parse_qs(parsed_req_url.query, keep_blank_values=True)
            query_params = {k: v[0] if len(v) == 1 else v for k, v in query_params_raw.items()}
            has_callback_param = "callback" in {k.lower() for k in query_params.keys()}

            raw_payload = None
            try:
                raw_payload = request.post_data
            except Exception:
                raw_payload = None

            body_payload, payload_format = _parse_body_payload(raw_payload)
            dedupe_key = _build_dedupe_key(method, request.url, query_params, body_payload)
            if dedupe_key in seen_keys:
                return

            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) < MIN_TEXTUAL_BODY_BYTES:
                        return
                    if int(content_length) > MAX_TEXT_READ_BYTES:
                        body_text = ""
                    else:
                        body_text = await response.text()
                except Exception:
                    body_text = ""
            else:
                try:
                    body_text = await response.text()
                except Exception:
                    body_text = ""

            body_shape = _detect_body_shape(body_text)
            parsed_jsonp = _extract_jsonp_payload(body_text) if body_shape == "jsonp_wrapper" else None
            body_analysis = analyze_candidate_body(
                body_text,
                body_shape=body_shape,
                content_type=content_type,
            )
            data_key_hits = body_analysis["data_key_hits"]

            if not _should_keep_candidate(
                url=request.url,
                body_text=body_text,
                body_shape=body_shape,
                has_callback_param=has_callback_param,
                data_key_hits=data_key_hits,
            ):
                return

            source_kind = _classify_source_kind(
                method=method,
                resource_type=resource_type,
                content_type=content_type,
                url=request.url,
                has_body_payload=body_payload is not None,
                body_shape=body_shape,
                has_callback_param=has_callback_param,
                data_key_hits=data_key_hits,
            )

            merged_payload: Dict[str, Any] = dict(query_params)
            if body_payload and isinstance(body_payload, dict):
                merged_payload.update(body_payload)

            candidate = {
                "api_index": api_index,
                "method_type": method,
                "type": resource_type,
                "source_kind": source_kind,
                "api_url": request.url,
                "headers": _sanitize_headers(dict(request.headers)),
                "payload": merged_payload,
                "query_params": query_params,
                "body_payload": body_payload,
                "payload_format": payload_format,
                "status": response.status,
                "content_type": content_type,
                "length": len(body_text),
                "sample": body_analysis["semantic_sample"] or _extract_informative_sample(
                    body_text,
                    limit=400,
                    parsed_jsonp=parsed_jsonp,
                ),
                "body_shape": body_shape,
                "has_callback_param": has_callback_param,
                "data_key_hits": data_key_hits,
                "semantic_record_count": body_analysis["semantic_record_count"],
                "title_date_pair_count": body_analysis["title_date_pair_count"],
                "has_repeated_records": body_analysis["has_repeated_records"],
                "has_notice_terms": body_analysis["has_notice_terms"],
                "analysis_kind": body_analysis["analysis_kind"],
            }

            seen_keys.add(dedupe_key)
            candidates.append(candidate)
            api_index += 1
            last_candidate_at = time.monotonic()
            logger.info("✅ 후보 수집 -> [%s] %s", method, request.url)

        page.on("response", capture_response)

        navigation_ok = False
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=goto_timeout_ms)
            await asyncio.to_thread(validate_public_url, page.url)
            navigation_ok = True
            logger.info("✅ [페이지 진입 성공] domcontentloaded 완료")
        except UnsafeUrlError:
            logger.warning("Playwright 최종 URL 보안 검증 실패: %s", page.url)
            await browser.close()
            return []
        except Exception:
            logger.warning("⚠️ [페이지 진입 경고] domcontentloaded timeout 또는 실패, 부분 응답 기준으로 계속 관측합니다.", exc_info=True)

        observe_started_at = time.monotonic()
        while True:
            elapsed = time.monotonic() - observe_started_at
            idle_for = time.monotonic() - last_candidate_at
            if elapsed >= max_observe_sec:
                break
            if elapsed >= min_observe_sec and len(candidates) >= enough_candidates and idle_for >= quiet_window_sec:
                logger.info("🛑 후보 충분 + 네트워크 정체 구간 감지로 조기 종료합니다.")
                break
            await asyncio.sleep(0.25)

        if navigation_ok:
            try:
                await page.wait_for_load_state("networkidle", timeout=1500)
            except Exception:
                pass

        await browser.close()
        logger.info("📦 후보 수집 종료 | target=%s | candidates=%d", target_url, len(candidates))
        return candidates
