import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright

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
TEXTUAL_CONTENT_TYPE_HINTS = (
    "text/html", "application/json", "text/json", "application/xml", "text/xml",
    "text/plain", "application/javascript", "text/javascript", "application/graphql-response+json"
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


def _extract_informative_sample(body: str, limit: int = 400) -> str:
    if not body:
        return ""

    compact = _normalize_whitespace(body)
    if not compact:
        return ""

    lower_compact = compact.lower()
    best_idx: Optional[int] = None
    for keyword in KEYWORD_HINTS:
        idx = lower_compact.find(keyword.lower())
        if idx != -1:
            best_idx = idx
            break

    if best_idx is None:
        return compact[:limit]

    start = max(0, best_idx - 120)
    return compact[start:start + limit]


def _classify_source_kind(
    method: str,
    resource_type: str,
    content_type: str,
    url: str,
    has_body_payload: bool,
) -> str:
    lowered_url = url.lower()
    if "graphql" in lowered_url:
        return "graphql"
    if resource_type == "document" and "text/html" in content_type:
        return "document_html"
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
    return f"{resource_type}_other"


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


def _looks_textual(content_type: str, resource_type: str) -> bool:
    if resource_type not in {"document", "fetch", "xhr"}:
        return False
    if not content_type:
        return True
    return any(hint in content_type for hint in TEXTUAL_CONTENT_TYPE_HINTS)


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
    - document / fetch / xhr / POST 후보를 폭넓게 수집합니다.
    - 시각적 리소스는 route abort로 실제 네트워크 비용도 줄입니다.
    """
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
            else:
                await route.continue_()

        await page.route("**/*", route_handler)

        async def capture_response(response):
            nonlocal api_index, last_candidate_at

            if len(candidates) >= MAX_CANDIDATES:
                return

            request = response.request
            method = request.method.upper()
            resource_type = request.resource_type

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
            if not _looks_textual(content_type, resource_type):
                return
            if response.status < 200 or response.status >= 400:
                return

            query_params_raw = parse_qs(parsed_req_url.query, keep_blank_values=True)
            query_params = {k: v[0] if len(v) == 1 else v for k, v in query_params_raw.items()}

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

            if body_text:
                snippet = body_text[:50].strip()
                if not (snippet.startswith("{") or snippet.startswith("[") or snippet.startswith("<")):
                    return

            source_kind = _classify_source_kind(
                method=method,
                resource_type=resource_type,
                content_type=content_type,
                url=request.url,
                has_body_payload=body_payload is not None,
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
                "sample": _extract_informative_sample(body_text, limit=400),
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
            navigation_ok = True
            logger.info("✅ [페이지 진입 성공] domcontentloaded 완료")
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
