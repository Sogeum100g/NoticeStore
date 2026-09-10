import asyncio

from fastapi import APIRouter, HTTPException, Depends, status
from typing import List

from repositories.notice_repo import (
    add_user_subscription, 
    get_user_specific_sites, 
    get_user_site_status,
    delete_user_subscription, 
    update_user_view_time,
    update_subscription_notification,
    update_site_crawl_state,
    insert_site,
    record_site_submission,
    select_site_id,
)
from repositories.user_repo import (
    get_user_max_sites_limit,             # 💡 한도 체크용 함수 임포트
    get_current_subscription_count  # 💡 구독 개수 체크용 함수 임포트
)
from schemas import SiteRequest, SiteResponse, SubscriptionNotificationRequest
from dependencies import get_current_user_id

from celery_app import scrape_target_site
from dataController.security.url_safety import UnsafeUrlError, validate_public_url
from services.site_error_service import (
    get_public_site_error_code,
    get_site_error_message,
)

# 라우터 태그 명확화
router = APIRouter(tags=["Subscriptions"])

@router.post("/add-site", response_model=SiteResponse)
async def add_new_site(
    request: SiteRequest,
    user_id: int = Depends(get_current_user_id) # 여기서 인증 실패 시 자동으로 401(NEED_LOGIN 대응 가능)
):
    # 1. 사이트 한도 체크 (플러터의 MAX_SITES_LIMIT와 일치)
    max_limit = get_user_max_sites_limit(user_id)
    current_count = get_current_subscription_count(user_id)

    if current_count >= max_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="MAX_SITES_LIMIT" 
        )

    # 2. URL을 먼저 검증하고 canonical URL로 pending 사이트를 확보합니다.
    try:
        validated = await asyncio.to_thread(validate_public_url, request.url)
    except UnsafeUrlError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="INVALID_URL",
        ) from exc

    canonical_url = validated.url
    site_id = select_site_id(canonical_url)
    if not site_id:
        from datetime import datetime, timezone

        site_id = insert_site(
            canonical_url,
            datetime.now(timezone.utc),
            submitted_url=request.url,
            crawl_status="pending",
            validation_status="valid",
        )

    if not site_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="DATABASE_ERROR"
        )
    record_site_submission(
        site_id,
        submitted_url=request.url,
        validation_status="valid",
    )

    # 3. 구독은 즉시 저장하고, 실제 분석/크롤링은 Celery에 위임합니다.
    try:
        subscription_saved = add_user_subscription(user_id, site_id, request.alias)
        if not subscription_saved:
            raise RuntimeError("subscription insert failed")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="DATABASE_ERROR"
        )

    site = get_user_site_status(user_id, site_id) or {}
    crawl_status = site.get("crawl_status", "pending")
    registration_completed = bool(site.get("registration_completed"))

    try:
        scrape_target_site.delay(site_id, canonical_url)
    except Exception as exc:
        # 이미 활성화된 사이트를 새로 구독한 경우에는 등록 자체가 완료된
        # 상태이므로 백그라운드 새로고침 큐 실패를 등록 실패로 바꾸지 않습니다.
        if registration_completed:
            return {
                "status": "success",
                "message": "ACTIVE",
                "site_id": site_id,
                "crawl_status": crawl_status,
                "registration_completed": True,
            }
        update_site_crawl_state(
            site_id,
            crawl_status="failed",
            validation_error_code="CRAWL_QUEUE_UNAVAILABLE",
            validation_error="크롤링 작업을 대기열에 등록하지 못했습니다.",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CRAWL_QUEUE_UNAVAILABLE",
        ) from exc

    # 기존 Flutter 호환을 위해 status=success를 유지합니다. 신규 등록은 PENDING,
    # 이미 활성화된 사이트 구독은 ACTIVE로 명확히 구분합니다.
    return {
        "status": "success",
        "message": "ACTIVE" if registration_completed else "PENDING",
        "site_id": site_id,
        "crawl_status": crawl_status,
        "registration_completed": registration_completed,
    }


@router.get("/subscriptions_sites")
async def read_favorite_sites(user_id: int = Depends(get_current_user_id)):
    """사용자가 현재 구독 중인 사이트 목록과 새로운 공지 유무를 반환합니다."""
    raw_data = get_user_specific_sites(user_id)  # (id, url, alias, has_new)

    return {
        "status": "success",
        "sites": [
            {
                "site_id": r[0],
                "url": r[1],
                "alias": r[2],
                "has_new": r[3],
                "crawl_status": r[4],
                "error_code": get_public_site_error_code(r[5]),
                "error_message": get_site_error_message(r[5]),
                "validation_error": r[6],
                "registration_completed": r[7],
                "notification_enabled": r[8],
            } for r in raw_data
        ]
    }


@router.get("/sites/{site_id}/status")
async def read_site_status(
    site_id: int,
    user_id: int = Depends(get_current_user_id),
):
    site = get_user_site_status(user_id, site_id)
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SITE_NOT_FOUND",
        )
    site = dict(site)
    stored_error_code = site.pop("validation_error_code", None)
    site["error_code"] = get_public_site_error_code(stored_error_code)
    site["error_message"] = get_site_error_message(stored_error_code)
    return {"status": "success", "site": site}


@router.delete("/subscriptions/{site_id}")
async def remove_subscription(
        site_id: int,
        user_id: int = Depends(get_current_user_id)
):
    """특정 사이트의 구독을 해지합니다."""
    try:
        is_deleted = delete_user_subscription(user_id, site_id)
        if not is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="해당 구독 정보를 찾을 수 없거나 이미 삭제되었습니다."
            )
        return {"status": "success", "message": "구독이 해지되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"구독 해지 중 오류가 발생했습니다: {str(e)}"
        )


@router.patch("/subscriptions/{site_id}/notification")
async def change_subscription_notification(
    site_id: int,
    request: SubscriptionNotificationRequest,
    user_id: int = Depends(get_current_user_id),
):
    """특정 구독의 수집 결과 알림을 켜거나 끕니다."""
    updated = update_subscription_notification(
        user_id,
        site_id,
        request.notification_enabled,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SUBSCRIPTION_NOT_FOUND",
        )
    return {
        "status": "success",
        "site_id": site_id,
        "notification_enabled": request.notification_enabled,
    }


@router.patch("/sites/{site_id}/view")
async def mark_as_read(
        site_id: int,
        user_id: int = Depends(get_current_user_id)
):
    """사이트를 확인했음을 기록하여 'N' 배지(새 소식 표시)를 지웁니다."""
    update_user_view_time(site_id, user_id)
    return {"status": "success", "message": "성공적으로 읽음 처리되었습니다."}
