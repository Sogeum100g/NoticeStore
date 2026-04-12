import os
import httpx
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, status

from repositories.inquiry_repo import insert_inquiry, get_user_inquiries, get_inquiry_by_id, update_inquiry_reply
from repositories.user_repo import get_user_fcm_tokens, get_user_info_by_id
# 분리해둔 스키마 및 의존성 임포트
from schemas import InquiryRequest, ReplyRequest
from dependencies import get_current_user_id, require_admin

# 서비스 및 DB 함수 임포트
from services.notify_service import send_fcm_notification


router = APIRouter(tags=["Inquiries"])

# --- [도움 함수: 외부 알림] ---

async def send_discord_notification(category: str, title: str, content: str, email: str, nickname: str):
    """새로운 문의 접수 시 디스코드 웹훅을 통해 관리자에게 실시간 알림을 보냅니다."""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return

    payload = {
        "embeds": [{
            "title": "📌 새로운 1:1 문의가 접수되었습니다!",
            "color": 0x3498db,
            "fields": [
                {"name": "분류", "value": category, "inline": True},
                {"name": "이메일", "value": email, "inline": True},
                {"name": "작성자", "value": nickname, "inline": True},
                {"name": "제목", "value": title, "inline": False},
                {"name": "내용", "value": content, "inline": False},
            ],
            "footer": {"text": "센트리피전 관리 시스템"},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }]
    }

    async with httpx.AsyncClient() as client:
        await client.post(webhook_url, json=payload)

# --- [사용자 전용 엔드포인트] ---

@router.post("/inquiries")
async def submit_inquiry(
    request: InquiryRequest,
    background_tasks: BackgroundTasks,
    user_id: int = Depends(get_current_user_id)
):
    """사용자가 새로운 문의를 등록합니다. 서버 부하 방지를 위해 디스코드 알림은 백그라운드 태스크로 처리합니다."""
    user_info = get_user_info_by_id(user_id)
    # 1. DB의 email, nickname 필드 확인
    email = user_info.get('email')
    nickname = user_info.get('nickname')
    

    # 2. 닉네임이 비어있다면 이메일 앞부분 추출 (Dart 로직과 동기화)
    if not nickname or not nickname.strip():
        email = user_info.get('email')
        if email and '@' in email:
            nickname = email.split('@')[0]
            

    success = insert_inquiry(user_id, request.category, request.title, request.content)

    if success:
        background_tasks.add_task(
            send_discord_notification,
            request.category, request.title, request.content, email, nickname
        )
        return {"status": "success"}
    else:
        raise HTTPException(status_code=500, detail="문의 저장에 실패했습니다.")


@router.get("/inquiries/me")
async def get_my_inquiries(user_id: int = Depends(get_current_user_id)):
    """사용자 본인이 작성한 문의 내역과 답변 여부를 조회합니다."""
    inquiries = get_user_inquiries(user_id)
    return {"status": "success", "data": inquiries}

# --- [관리자 전용 엔드포인트] ---
@router.patch("/admin/inquiries/{inquiry_id}/reply")
async def reply_to_inquiry(
        inquiry_id: int,
        request: ReplyRequest,
        admin_id: int = Depends(require_admin)
):
    """관리자가 답변을 등록하면 해당 유저의 '모든 기기'에 FCM 푸시 알림을 발송합니다."""
    # 1. 문의 존재 여부 확인
    inquiry = get_inquiry_by_id(inquiry_id)
    if not inquiry:
        raise HTTPException(status_code=404, detail="해당 문의를 찾을 수 없습니다.")

    # 2. DB에 답변 내용 업데이트
    success = update_inquiry_reply(inquiry_id, request.reply_content)

    if success:
        target_user_id = inquiry['user_id']
        
        # 3. [핵심 수정] 사용자의 알림 수신 설정 확인 [cite: 2026-03-10]
        user_info = get_user_info_by_id(target_user_id)
        if user_info and user_info.get('is_notification_enabled'):
            
            # 4. [핵심 수정] 사용자의 모든 기기 토큰 조회 ($1:N$ 대응) [cite: 2026-03-10]
            tokens = get_user_fcm_tokens(target_user_id)
            
            if tokens:
                for token_data in tokens:
                    fcm_token = token_data.get('fcm_token')
                    if fcm_token:
                        send_fcm_notification(
                            fcm_token=fcm_token,
                            title="1:1 문의 답변이 등록되었습니다.",
                            body=f"[{inquiry['title']}] 문의에 대한 답변을 확인해보세요.",
                            data={"screen": "inquiry_detail", "inquiry_id": str(inquiry_id)}
                        )
        
        return {"status": "success", "message": "답변이 등록되었습니다."}
    else:
        raise HTTPException(status_code=500, detail="답변 등록에 실패했습니다.")