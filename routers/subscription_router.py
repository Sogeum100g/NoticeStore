from fastapi import APIRouter, HTTPException, Depends, status
from typing import List

from repositories.notice_repo import (
    add_user_subscription, 
    get_user_specific_sites, 
    delete_user_subscription, 
    update_user_view_time,
)
from repositories.user_repo import (
    get_user_max_sites_limit,             # 💡 한도 체크용 함수 임포트
    get_current_subscription_count  # 💡 구독 개수 체크용 함수 임포트
)
from schemas import SiteRequest, SiteResponse
from dependencies import get_current_user_id

from scrape.dataController.scrape_auto import run_full_scrape

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

    # 2. 크롤링 실행
    result = await run_full_scrape(request.url)
    scrape_status = result.get('status')
    site_id = result.get('site_id')

    # 3. 결과 상태별 분기 (플러터의 ROBOTS_TXT_BLOCKED 등과 일치)
    if scrape_status == "blocked":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="ROBOTS_TXT_BLOCKED"
        )
    
    if scrape_status == "error" or not site_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="CRAWLING_ERROR" # 필요 시 플러터 스위치문에 추가 가능
        )

    # 4. DB 저장
    try:
        add_user_subscription(user_id, site_id, request.alias)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="DATABASE_ERROR"
        )

    # 5. 성공 응답 (플러터가 기대하는 success 구조)
    return {
        "status": "success",
        "message": "SUCCESS",
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