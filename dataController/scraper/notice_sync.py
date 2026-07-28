import logging
import hashlib
import json
from typing import Any, Dict, List, Optional

try:
    from repositories import notice_repo
except ImportError:  # pragma: no cover
    import sys
    from pathlib import Path
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.append(str(PROJECT_ROOT))
    from repositories import notice_repo

try:
    from .page_extractors import expand_url
except ImportError:  # pragma: no cover
    from dataController.scraper.page_extractors import expand_url

logger = logging.getLogger(__name__)


def sync_notices_to_db(site_id: int, notices: List[Dict[str, Any]], new_hash: str, api_url: str) -> None:
    for notice in notices:
        detail_url = notice.get("detail_url")
        external_id = notice.get("external_id")
        published_at = notice.get("published_at") or notice.get("created_at")
        record_hash = notice.get("record_hash")
        if not record_hash:
            identity = {
                "external_id": external_id,
                "detail_url": detail_url,
                "title": notice.get("title"),
                "published_at": str(published_at or ""),
            }
            record_hash = hashlib.sha256(
                json.dumps(
                    identity,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()

        notice_repo.insert_or_update_notice(
            site_id=site_id,
            title=notice.get("title"),
            author=notice.get("author"),
            url=notice.get("url"),
            created_at=None,
            scraped_at=notice.get("scraped_at"),
            is_active=True,
            detail_url=detail_url,
            external_id=external_id,
            published_at=published_at,
            content_type=notice.get("content_type") or "notice",
            record_hash=record_hash,
        )
    notice_repo.deactivate_old_notices(site_id)
    notice_repo.update_api(api_url=api_url, last_hash=new_hash)


def get_recent_info(url: str) -> Dict[str, Any]:
    logger.info("DB에서 기존 데이터 조회하여 반환합니다.")
    url = expand_url(url)

    try:
        raw_data = notice_repo.get_all_notices(url)
        site_id = notice_repo.select_site_id(url)

        if not raw_data:
            logger.warning("DB에 저장된 기존 데이터가 없습니다: %s", url)
            return {"status": "empty", "site_id": site_id, "notices": []}

        formatted_notices = []
        for row in raw_data:
            notice_id, title, author, notice_url, created_at, scraped_at = row

            formatted_notices.append(
                {
                    "notice_id": notice_id,
                    "title": title,
                    "author": author or "",
                    "url": notice_url,
                    "created_at": created_at.isoformat() if created_at else "",
                    "scraped_at": scraped_at.isoformat() if scraped_at else "",
                }
            )

        return {"status": "success", "site_id": site_id, "notices": formatted_notices}

    except Exception as e:
        logger.error("❌ DB 조회 중 에러 발생 (URL: %s): %s", url, e)
        return {"status": "error", "site_id": None, "notices": []}


def process_notice_request(input_url: str) -> Dict[str, Any]:
    final_url = expand_url(input_url)
    return get_recent_info(final_url)
