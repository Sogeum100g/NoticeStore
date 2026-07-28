import logging
import re
from typing import Any, Dict, List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

TITLE_KEYS = {"title"}
DATE_KEYS = {"date"}
COUNT_KEYS = {"count"}
LIST_KEYS = {"list"}
NEGATIVE_URL_HINTS = (
    "analytics", "telemetry", "gtm", "google-analytics", "doubleclick", "hotjar", "sentry",
    "facebook", "pixel", "collect", "beacon", "metrics", "tracking", "hashtag"
)
NON_CONTENT_URL_HINTS = (
    "airbridge", "/config", "captcha", "/login/", "pcbang-check", "/logos",
    "/events/web/", "mediacategory", "redirecturl",
)
STATIC_ASSET_HINTS = (
    "jquery", "swiper", "analytics.js", "gtm.js", "ui.common", "language.js", "aos.js"
)
LEGACY_ENDPOINT_HINTS = (".fo", ".do", ".data", ".action", ".ajax")


def _has_any_key(hits: List[str], keys: set[str]) -> bool:
    return any(hit in keys for hit in hits)


def _count_matching_keys(hits: List[str], keys: set[str]) -> int:
    return sum(1 for hit in hits if hit in keys)


def _looks_like_telemetry(candidate: Dict[str, Any]) -> bool:
    url = (candidate.get("api_url") or "").lower()
    sample = (candidate.get("sample") or "").lower()
    if any(hint in url for hint in NEGATIVE_URL_HINTS):
        return True
    if candidate.get("has_repeated_records"):
        return False
    return any(hint in sample for hint in NEGATIVE_URL_HINTS)


def _looks_like_static_asset(candidate: Dict[str, Any]) -> bool:
    url = (candidate.get("api_url") or "").lower()
    source_kind = candidate.get("source_kind") or ""
    if source_kind in {"script_other", "document_other"} and not candidate.get("data_key_hits"):
        return True
    return any(hint in url for hint in STATIC_ASSET_HINTS)


def _looks_like_non_content(candidate: Dict[str, Any]) -> bool:
    url = (candidate.get("api_url") or "").lower()
    if candidate.get("has_repeated_records"):
        return False
    return any(hint in url for hint in NON_CONTENT_URL_HINTS)


def _normalized_url(url: str) -> str:
    parsed = urlparse(url or "")
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def _is_exact_target(target_url: str, api_url: str) -> bool:
    return _normalized_url(target_url) == _normalized_url(api_url)


def _same_host(target_url: str, api_url: str) -> bool:
    return urlparse(target_url).netloc.lower() == urlparse(api_url).netloc.lower()


def _build_features(candidate: Dict[str, Any], target_url: str) -> Dict[str, Any]:
    source_kind = candidate.get("source_kind") or ""
    resource_type = candidate.get("type") or ""
    method = (candidate.get("method_type") or "GET").upper()
    content_type = (candidate.get("content_type") or "").lower()
    api_url = candidate.get("api_url") or ""
    data_key_hits = candidate.get("data_key_hits") or []
    body_shape = candidate.get("body_shape") or ""
    sample = candidate.get("sample") or ""
    payload = candidate.get("payload") or {}

    features = {
        "is_exact_target": _is_exact_target(target_url, api_url),
        "is_same_host": _same_host(target_url, api_url),
        "is_document_html": source_kind == "document_html",
        "is_json_like": body_shape in {"json_object", "json_array"} or "json" in content_type,
        "is_jsonp_like": source_kind == "jsonp_javascript" or body_shape == "jsonp_wrapper",
        "is_javascript_bridge": source_kind in {"bridge_javascript", "script_data"},
        "has_callback_param": bool(candidate.get("has_callback_param")),
        "has_title_key": _has_any_key(data_key_hits, TITLE_KEYS),
        "title_key_count": _count_matching_keys(data_key_hits, TITLE_KEYS),
        "has_date_key": _has_any_key(data_key_hits, DATE_KEYS),
        "date_key_count": _count_matching_keys(data_key_hits, DATE_KEYS),
        "has_total_count": _has_any_key(data_key_hits, COUNT_KEYS),
        "has_list_key": _has_any_key(data_key_hits, LIST_KEYS),
        "data_key_hits_count": len(data_key_hits),
        "looks_like_telemetry": _looks_like_telemetry(candidate),
        "looks_like_static_asset": _looks_like_static_asset(candidate),
        "looks_like_non_content": _looks_like_non_content(candidate),
        "legacy_endpoint_hint": any(h in api_url.lower() for h in LEGACY_ENDPOINT_HINTS),
        "resource_is_data_channel": resource_type in {"document", "fetch", "xhr", "script"},
        "is_post": method == "POST",
        "sample_length_ok": len(sample) >= 80,
        "query_or_body_key_count": len(payload) if isinstance(payload, dict) else 0,
        "has_repeated_records": bool(candidate.get("has_repeated_records")),
        "semantic_record_count": int(candidate.get("semantic_record_count") or 0),
        "title_date_pair_count": int(candidate.get("title_date_pair_count") or 0),
        "has_notice_terms": bool(candidate.get("has_notice_terms")),
        "body_shape": body_shape,
    }
    return features


def _score_candidate(candidate: Dict[str, Any], features: Dict[str, Any]) -> tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []
    source_kind = candidate.get("source_kind") or ""
    api_url = (candidate.get("api_url") or "").lower()

    if features["looks_like_static_asset"]:
        score -= 30
        reasons.append("정적 asset 신호")
    if features["looks_like_telemetry"]:
        score -= 35
        reasons.append("telemetry/analytics 신호")
    if features["looks_like_non_content"]:
        score -= 30
        reasons.append("설정/인증/SDK 보조 응답 신호")

    source_kind_bonus = {
        "jsonp_javascript": 8,
        "xhr_json": 8,
        "post_json": 8,
        "graphql": 8,
        "form_post": 6,
        "bridge_javascript": 6,
        "script_data": 6,
        "xhr_html": 5,
        "document_html": 5,
    }
    bonus = source_kind_bonus.get(source_kind, 0)
    if bonus:
        score += bonus
        reasons.append(f"source_kind={source_kind} 가산")

    if features["resource_is_data_channel"]:
        score += 2
        reasons.append("데이터 채널 resource_type")
    if features["is_exact_target"]:
        score += 24
        reasons.append("등록 대상 URL과 정확히 일치")
    if features["is_same_host"]:
        score += 8
        reasons.append("동일 host")
    if features["is_post"]:
        score += 1
        reasons.append("POST 요청")
    if features["is_json_like"]:
        score += 3
        reasons.append("JSON 계열 body")
    if features["is_jsonp_like"]:
        score += 1
        reasons.append("JSONP wrapper")
    if features["is_javascript_bridge"]:
        score += 2
        reasons.append("데이터성 JavaScript bridge")
    if features["has_callback_param"]:
        score += 1
        reasons.append("callback 파라미터")
    if features["legacy_endpoint_hint"]:
        score += 2
        reasons.append("레거시 데이터 endpoint 힌트")
    if features["has_title_key"]:
        score += 8
        reasons.append("제목 계열 키 존재")
    if features["has_date_key"]:
        score += 5
        reasons.append("날짜 계열 키 존재")
    if features["has_total_count"]:
        score += 2
        reasons.append("count 계열 키 존재")
    if features["has_list_key"]:
        score += 3
        reasons.append("list 계열 키 존재")
    if features["sample_length_ok"]:
        score += 1
    if features["query_or_body_key_count"] >= 3:
        score += 1
        reasons.append("query/body key 수 충분")

    if features["has_repeated_records"]:
        score += 30
        score += min(features["semantic_record_count"], 10)
        reasons.append(
            f"반복 목록 레코드 증거({features['semantic_record_count']}건)"
        )
    elif not features["is_exact_target"]:
        score -= 8
        reasons.append("반복 목록 레코드 증거 없음")

    if features["title_date_pair_count"] >= 2:
        score += 8
        reasons.append("반복 제목-날짜 쌍 존재")
    if features["has_notice_terms"]:
        score += 3
        reasons.append("공지/게시물 문맥 존재")
    if not features["is_same_host"] and not features["has_repeated_records"]:
        score -= 4
        reasons.append("외부 host이며 목록 증거 없음")
    if features["is_document_html"] and not features["has_repeated_records"]:
        score -= 6
        reasons.append("HTML이지만 반복 목록 증거가 약함")
    if source_kind == "script_other":
        score -= 10
        reasons.append("일반 script 후보")
    if re.search(r"(?:jquery|min\.js|bundle|chunk)", api_url) and not features["has_title_key"]:
        score -= 12
        reasons.append("라이브러리/번들 JS 패턴")

    return score, reasons


def build_candidate_pool(
    ranked_candidates: List[Dict[str, Any]],
    target_url: str,
    *,
    limit: int = 4,
) -> List[Dict[str, Any]]:
    """점수 순위와 무관하게 정답 URL·의미 후보·동일 출처 후보를 보존한다."""
    if limit <= 0:
        return []

    selected: List[Dict[str, Any]] = []
    seen_indexes = set()

    def add(candidate: Dict[str, Any]) -> None:
        index = candidate.get("api_index")
        if index in seen_indexes or len(selected) >= limit:
            return
        selected.append(candidate)
        seen_indexes.add(index)

    exact_target = next(
        (
            item
            for item in ranked_candidates
            if (item.get("features") or {}).get("is_exact_target")
            or _is_exact_target(target_url, item.get("api_url") or "")
        ),
        None,
    )
    if exact_target:
        add(exact_target)

    for item in ranked_candidates:
        if (item.get("features") or {}).get("has_repeated_records"):
            add(item)
            break

    for item in ranked_candidates:
        features = item.get("features") or {}
        if features.get("is_same_host") and not features.get("looks_like_non_content"):
            add(item)
            break

    for item in ranked_candidates:
        add(item)

    return sorted(
        selected,
        key=lambda item: (item.get("score", 0), item.get("length", 0)),
        reverse=True,
    )


def rank_candidates(candidates: List[Dict[str, Any]], target_url: str) -> List[Dict[str, Any]]:
    ranked: List[Dict[str, Any]] = []
    for candidate in candidates:
        features = _build_features(candidate, target_url)
        score, score_reasons = _score_candidate(candidate, features)
        enriched = dict(candidate)
        enriched["features"] = features
        enriched["score"] = score
        enriched["score_reasons"] = score_reasons
        ranked.append(enriched)

    ranked.sort(key=lambda item: (item.get("score", 0), item.get("length", 0)), reverse=True)
    logger.info("📊 후보 스코어링 완료 | candidates=%d", len(ranked))
    for item in ranked[:5]:
        logger.info(
            "  - rank api_index=%s score=%s source_kind=%s url=%s",
            item.get("api_index"), item.get("score"), item.get("source_kind"), item.get("api_url")
        )
    return ranked
