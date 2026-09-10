import logging
import hashlib
import json
from typing import Any, Dict, List, Optional

from repositories import notice_repo
from dataController.scraper.navigation.fetch_policy import expand_url
from dataController.scraper.navigation.url_normalizer import (
    canonicalize_notice_detail_url,
)

logger = logging.getLogger(__name__)


def sync_notices_to_db(
    site_id: int,
    notices: List[Dict[str, Any]],
    new_hash: str,
    api_url: str,
    crawl_run_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Atomically sync the legacy extraction path and create push events."""
    conn = notice_repo.get_db_connection()
    if not conn:
        raise RuntimeError("공지 동기화를 위한 DB 연결이 없습니다.")

    persisted_notice_ids = set()
    new_notice_ids: List[int] = []
    try:
        with conn.cursor() as cur:
            for notice in notices:
                detail_url = canonicalize_notice_detail_url(notice.get("detail_url"))
                external_id = notice.get("external_id")
                published_at = notice.get("published_at")
                record_hash = notice.get("record_hash")
                if not record_hash:
                    identity = {
                        "external_id": external_id,
                        "detail_url": detail_url,
                        "title": notice.get("title"),
                        "author": notice.get("author"),
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

                notice_id, was_inserted = (
                    notice_repo._insert_or_update_notice_result_with_cursor(
                        cur,
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
                )
                if not notice_id:
                    raise RuntimeError(
                        "공지를 DB에 저장하지 못했습니다. "
                        f"site_id={site_id}, external_id={external_id}, "
                        f"detail_url={detail_url}"
                    )
                if notice_id in persisted_notice_ids:
                    raise RuntimeError(
                        "서로 다른 추출 레코드가 동일한 DB 공지로 합쳐졌습니다. "
                        f"site_id={site_id}, notice_id={notice_id}"
                    )
                persisted_notice_ids.add(notice_id)
                if was_inserted:
                    new_notice_ids.append(notice_id)

            cur.execute(
                """
                UPDATE notices
                SET is_active = false
                WHERE site_id = %s
                  AND is_active = true
                  AND created_at < CURRENT_TIMESTAMP - INTERVAL '3 months';
                """,
                (site_id,),
            )
            cur.execute(
                """
                UPDATE api
                SET last_hash = %s,
                    last_observed_hash = %s,
                    last_processed_hash = %s,
                    processing_status = 'success',
                    retry_count = 0,
                    next_retry_at = NULL,
                    last_error = NULL,
                    scraped_at = NOW()
                WHERE api_url = %s;
                """,
                (new_hash, new_hash, new_hash, api_url),
            )
            event_ids = notice_repo.create_notification_events_with_cursor(
                cur,
                site_id=site_id,
                crawl_run_id=crawl_run_id,
                new_notice_ids=new_notice_ids,
            )
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    logger.info(
        "공지 동기화 완료 | site_id=%s extracted=%d persisted=%d new=%d",
        site_id,
        len(notices),
        len(persisted_notice_ids),
        len(new_notice_ids),
    )
    return {
        "persisted_notice_count": len(persisted_notice_ids),
        "new_notice_ids": new_notice_ids,
        "new_notice_count": len(new_notice_ids),
        "notification_event_ids": event_ids,
    }


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
