"""YouTube community-post extraction helpers."""

from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Optional

import pytz
from bs4 import BeautifulSoup

from dataController.youtube_community import (
    extract_yt_initial_data,
    iter_youtube_community_posts,
)

def extract_yt_data(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
    for script_tag in soup.find_all("script"):
        initial_data = extract_yt_initial_data(script_tag.string or "")
        if initial_data is not None:
            return initial_data
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

    for post in iter_youtube_community_posts(yt_data):
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



__all__ = [
    "determine_created_at",
    "extract_yt_data",
    "parse_youtube_community_data",
]
