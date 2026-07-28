import asyncio
import datetime
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import robotparser
from urllib.parse import parse_qs, unquote, urlparse

import pytz
import requests
from bs4 import BeautifulSoup, Comment

from dataController.security.url_safety import (
    UnsafeUrlError,
    safe_request,
    validate_public_url,
)

logger = logging.getLogger(__name__)

CURRENT_DIR = Path(__file__).resolve().parent
PARENT_DIR = CURRENT_DIR.parent
TAG_PATH = PARENT_DIR / "tag.json"

with open(TAG_PATH, "r", encoding="utf-8") as json_file:
    tag_data = json.load(json_file)


def extract_next_data(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
    script_tag = soup.find("script", id="__NEXT_DATA__")
    if script_tag:
        try:
            return json.loads(script_tag.string)
        except json.JSONDecodeError:
            return None
    return None


def extract_yt_data(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
    script_tag = soup.find("script", string=re.compile(r"var ytInitialData ="))
    if script_tag:
        try:
            json_text = re.search(r"var ytInitialData = (\{.*?\});", script_tag.string).group(1)
            return json.loads(json_text)
        except (AttributeError, json.JSONDecodeError):
            return None
    return None


def determine_created_at(time_str: str, text_content: str) -> str:
    now = datetime.datetime.now(pytz.timezone("Asia/Seoul"))

    match_abs = re.search(r"(20\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})", text_content or "")
    if match_abs:
        y, m, d = match_abs.groups()
        return f"{y}-{int(m):02d}-{int(d):02d}T00:00:00+09:00"

    if not time_str:
        return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    numbers = [int(s) for s in re.findall(r"\d+", time_str)]
    num = numbers[0] if numbers else 0

    delta = datetime.timedelta()
    is_long_term = False

    if "분" in time_str:
        delta = datetime.timedelta(minutes=num)
    elif "시간" in time_str:
        delta = datetime.timedelta(hours=num)
    elif "일" in time_str:
        delta = datetime.timedelta(days=num)
        is_long_term = True
    elif "주" in time_str:
        delta = datetime.timedelta(weeks=num)
        is_long_term = True
    elif "개월" in time_str:
        delta = datetime.timedelta(days=num * 30)
        is_long_term = True
    elif "년" in time_str:
        delta = datetime.timedelta(days=num * 365)
        is_long_term = True
    else:
        return now.isoformat()

    past_time = now - delta
    if is_long_term:
        past_time = past_time.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        past_time = past_time.replace(minute=0, second=0, microsecond=0)
    return past_time.strftime("%Y-%m-%dT%H:%M:%S+09:00")


def parse_youtube_community_data(yt_data: Dict[str, Any], target_url: str) -> List[Dict[str, str]]:
    notices: List[Dict[str, str]] = []
    now = datetime.datetime.now(pytz.timezone("Asia/Seoul"))
    current_time_iso = now.isoformat()

    def find_posts(obj):
        if isinstance(obj, dict):
            if "backstagePostRenderer" in obj:
                yield obj["backstagePostRenderer"]
            for v in obj.values():
                yield from find_posts(v)
        elif isinstance(obj, list):
            for item in obj:
                yield from find_posts(item)

    for post in find_posts(yt_data):
        try:
            content_runs = post.get("contentText", {}).get("runs", [])
            full_text = "".join([run.get("text", "") for run in content_runs]).strip()
            if not full_text:
                continue

            author = post.get("authorText", {}).get("runs", [{}])[0].get("text", "")
            post_id = post.get("postId")
            url = f"https://www.youtube.com/post/{post_id}" if post_id else target_url

            time_runs = post.get("publishedTimeText", {}).get("runs", [])
            raw_time = time_runs[0].get("text", "") if time_runs else ""
            created_at = determine_created_at(raw_time, full_text)

            notices.append(
                {
                    "title": full_text,
                    "author": author,
                    "created_at": created_at,
                    "scraped_at": current_time_iso,
                    "url": url,
                }
            )
        except Exception:
            continue

    return notices


def remove_json_nulls(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: remove_json_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [remove_json_nulls(item) for item in obj]
    return obj


def preprocessing(soup: BeautifulSoup) -> str:
    for element in soup.find_all(tag_data["trash_tags"]):
        element.decompose()

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    return soup.get_text(separator="\n", strip=True)


def clean_html_text(raw_data: str) -> str:
    clean = re.sub(r"[\"']?\w+[\"']?\s*[:=]\s*(null|none|nan|undefined),?", "", raw_data, flags=re.IGNORECASE)
    clean = re.sub(r",+", ",", clean)
    return clean.replace(",}", "}").replace(",]", "]").strip()


def build_parser_text(response_text: str, parser_name: str = "lxml") -> str:
    soup = BeautifulSoup(response_text, parser_name)
    try:
        return clean_html_text(preprocessing(soup))
    finally:
        soup.decompose()


def normalize_string(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\W+", "", text).lower()


def get_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def expand_url(short_url: str) -> str:
    try:
        session = requests.Session()
        response = safe_request(
            session,
            "HEAD",
            short_url,
            timeout=12,
            max_redirects=5,
            max_response_bytes=1,
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
