from fastapi import APIRouter, HTTPException, Depends, status
from typing import List

from repositories.notice_repo import add_user_subscription, get_user_specific_sites, delete_user_subscription, \
    update_user_view_time
# 분리해둔 스키마 및 의존성 임포트
from schemas import SiteRequest
from dependencies import get_current_user_id

# DB 및 크롤링 핵심 함수 임포트

from scrape.dataController.scrape_auto import run_full_scrape

# 구독 및 사이트 관련 경로를 담당하는 라우터
router = APIRouter(tags=["Subscriptions"])


@router.post("/add-site")
async def add_new_site(
        request: SiteRequest,
        user_id: int = Depends(get_current_user_id)
):
    """
    새로운 사이트 URL을 입력받아 즉시 크롤링을 수행하고 구독 목록에 추가합니다.

    """
    # 1. 사이트 크롤링 및 사이트 테이블 등록 (내부적으로 sites 테이블 처리)
    result = await run_full_scrape(request.url)
    site_id = result.get('site_id')

    if not site_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="사이트 등록 및 초기 크롤링에 실패했습니다."
        )

    # 2. 구독 테이블(user_subscriptions)에 관계 저장
    add_user_subscription(user_id, site_id, request.alias)

    return {
        "status": "success",
        "message": "구독 목록에 성공적으로 추가되었습니다.",
        "site_id": site_id
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
                "has_new": r[3]
            } for r in raw_data
        ]
    }


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
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"구독 해지 중 오류가 발생했습니다: {str(e)}"
        )


@router.patch("/sites/{site_id}/view")
async def mark_as_read(
        site_id: int,
        user_id: int = Depends(get_current_user_id)
):
    """사이트를 확인했음을 기록하여 'N' 배지(새 소식 표시)를 지웁니다."""
    update_user_view_time(site_id, user_id)
    return {"status": "success", "message": "성공적으로 읽음 처리되었습니다."}