"""URL expansion and robots.txt fetch policy."""

from __future__ import annotations

import asyncio
import logging
from urllib import robotparser
from urllib.parse import parse_qs, unquote, urlparse

import requests

from dataController.security.url_safety import (
    UnsafeUrlError,
    safe_request,
    validate_public_url,
)

logger = logging.getLogger(__name__)

def expand_url(short_url: str) -> str:
    try:
        session = requests.Session()
        response = safe_request(
            session,
            "GET",
            short_url,
            timeout=12,
            max_redirects=5,
            max_response_bytes=1,
            read_body=False,
        )
        expanded_url = response.url
        response.close()
        parsed_url = urlparse(expanded_url)

        if "link.naver.com" in parsed_url.netloc:
            query_params = parse_qs(parsed_url.query)
            if "url" in query_params:
                clean_url = unquote(query_params["url"][0])
                clean_url = validate_public_url(clean_url).url
                logger.info("🔗 브릿지 파싱 완료: %s", clean_url)
                return clean_url

        return expanded_url
    except (requests.RequestException, UnsafeUrlError) as e:
        logger.error("❌ URL 전개 실패: %s", e)
        return short_url


async def is_crawling_allowed(url: str, user_agent: str = "*") -> bool:
    try:
        validated = await asyncio.to_thread(validate_public_url, url)
    except UnsafeUrlError as exc:
        logger.warning("robots.txt 확인 전 URL 보안 검증 실패: %s", exc)
        return False

    parsed_url = urlparse(validated.url)
    robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"
    rp = robotparser.RobotFileParser()
    try:
        rp.set_url(robots_url)
        session = requests.Session()
        response = await asyncio.to_thread(
            safe_request,
            session,
            "GET",
            robots_url,
            timeout=8,
            max_redirects=3,
            max_response_bytes=256_000,
        )
        response.encoding = response.apparent_encoding or "utf-8"
        rp.parse(response.text.splitlines())
        response.close()
    except Exception as e:
        logger.debug("robots.txt 확인 불가 (기본 허용): %s", e)
        return True
    return rp.can_fetch(user_agent, validated.url)

__all__ = ["expand_url", "is_crawling_allowed"]
