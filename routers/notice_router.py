from fastapi import APIRouter, HTTPException, Depends, status
from typing import List

from repositories.notice_repo import (
    get_all_user_notices,
    hide_user_notice,
    add_user_subscription,
    get_user_specific_sites,
    delete_user_subscription,
    update_user_view_time
)
# 분리해둔 스키마 및 의존성 임포트
from schemas import SiteRequest
from dependencies import get_current_user_id

# DB 및 크롤링 핵심 함수 임포트

from scrape.dataController.scrape_auto import run_full_scrape

router = APIRouter(tags=["Notices & Sites"])

# --- [공지사항 관련] ---

@router.get("/notices")
async def read_notices(user_id: int = Depends(get_current_user_id)):
    """로그인한 유저가 구독 중인 모든 사이트의 공지사항 목록을 조회합니다."""
    raw_data = get_all_user_notices(user_id)

    formatted_notices = []
    for row in raw_data:
        formatted_notices.append({
            "notice_id": row[0],
            "title": row[1],
            "author": row[2] or "",
            "url": row[3],
            "content_preview": row[4] or "",
            "created_at": row[5].isoformat() if row[5] else "",
            "scraped_at": row[6].isoformat() if row[6] else "",
            "site_id": row[7]
        })

    return {"status": "success", "notices": formatted_notices}


@router.delete("/notices/{notice_id}", status_code=status.HTTP_200_OK)
async def delete_notice(
    notice_id: int,
    user_id: int = Depends(get_current_user_id)
):
    """사용자가 특정 공지사항을 목록에서 숨김(삭제) 처리합니다."""
    success = hide_user_notice(user_id, notice_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="공지 삭제 처리에 실패했습니다."
        )
    return {"status": "success", "message": "공지가 성공적으로 삭제되었습니다."}


# --- [사이트 및 구독 관련] ---

@router.post("/add-site")
async def add_new_site(
    request: SiteRequest,
    user_id: int = Depends(get_current_user_id)
):
    """새로운 사이트 URL을 입력받아 크롤링 후 구독 목록에 추가합니다."""
    # 1. 사이트 크롤링 및 사이트 테이블 등록
    result = await run_full_scrape(request.url)
    site_id = result.get('site_id')

    if not site_id:
        raise HTTPException(status_code=500, detail="사이트 등록 및 크롤링 실패")

    # 2. 유저-사이트 구독 관계 저장
    add_user_subscription(user_id, site_id, request.alias)

    return {
        "status": "success",
        "message": "구독 목록에 성공적으로 추가되었습니다.",
        "site_id": site_id
    }


@router.get("/subscriptions_sites")
async def read_favorite_sites(user_id: int = Depends(get_current_user_id)):
    """사용자가 현재 구독 중인 사이트 목록과 새 글 유무를 확인합니다."""
    raw_data = get_user_specific_sites(user_id) 
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
                status_code=404,
                detail="해당 구독 정보를 찾을 수 없습니다."
            )
        return {"status": "success", "message": "구독이 해지되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")


@router.patch("/sites/{site_id}/view")
async def mark_as_read(
    site_id: int,
    user_id: int = Depends(get_current_user_id)
):
    """특정 사이트의 공지사항을 확인했음을 기록하여 '새 소식' 표시를 지웁니다."""
    update_user_view_time(site_id, user_id)
    return {"status": "success", "message": "읽음 처리 완료"}