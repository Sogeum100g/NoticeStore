from fastapi import APIRouter, HTTPException, Depends, status
from repositories.notice_repo import get_all_user_notices, hide_user_notice
from dependencies import get_current_user_id

# 라우터 태그 명확화
router = APIRouter(tags=["Notices"])

@router.get("/notices")
async def read_notices(user_id: int = Depends(get_current_user_id)):
    """로그인한 유저가 구독 중인 모든 사이트의 공지사항 목록을 조회합니다."""
    raw_data = get_all_user_notices(user_id)

    formatted_notices = []
    for row in raw_data:
        formatted_notices.append({
            "notice_id": row['notice_id'],
            "title": row['title'],
            "author": row['author'] or "",
            "url": row['url'],
            "published_at": row['published_at'].isoformat() if row['published_at'] else "",
            "created_at": row['created_at'].isoformat() if row['created_at'] else "",
            "scraped_at": row['scraped_at'].isoformat() if row['scraped_at'] else "",
            "site_id": row['site_id'],
            "is_new": bool(row['is_new']),
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
