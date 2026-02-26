from fastapi import APIRouter, HTTPException, Depends

from repositories.user_repo import update_user_nickname, get_user_info_by_id, update_user_notification_settings, \
    update_user_fcm_token
from schemas import NicknameRequest, NotificationSettingsRequest, FCMTokenRequest

# DB 및 의존성 함수 임포트

from dependencies import get_current_user_id


# APIRouter 객체 생성 (v1/user 하위 경로를 모두 담당)
router = APIRouter(prefix="/user", tags=["Users"])

@router.patch("/nickname")
async def change_nickname(
        request: NicknameRequest,
        user_id: int = Depends(get_current_user_id)
):
    """사용자의 닉네임을 변경하는 엔드포인트"""
    try:
        is_updated = update_user_nickname(user_id, request.nickname)
        if not is_updated:
            raise HTTPException(status_code=500, detail="닉네임 업데이트에 실패했습니다.")

        return {
            "status": "success",
            "message": "닉네임이 성공적으로 변경되었습니다.",
            "nickname": request.nickname
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서버 에러: {str(e)}")


@router.get("/profile")
async def get_user_profile(user_id: int = Depends(get_current_user_id)):
    """사용자의 프로필 및 알림 설정을 조회하는 엔드포인트"""
    try:
        user_info = get_user_info_by_id(user_id)
        if not user_info:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        return {
            "status": "success",
            "user": {
                "user_id": user_info["user_id"],
                "email": user_info["email"],
                "nickname": user_info["nickname"],
                "provider": user_info["provider"],
                "social_id": user_info.get("social_id"),
                "fcm_token": user_info.get("fcm_token"),
                "is_notification_enabled": user_info.get("is_notification_enabled", False),
                "notification_time": user_info.get("notification_time", "18:00")
            }
        }
    except KeyError as e:
        print(f"❌ [키 에러] DB 응답에 {e} 키가 없습니다!")
        raise HTTPException(status_code=500, detail=f"내부 데이터 매핑 에러: {e}")
    except Exception as e:
        print(f"❌ [서버 에러] {e}")
        raise HTTPException(status_code=500, detail="프로필 조회 중 오류가 발생했습니다.")


@router.patch("/notification")
async def update_notification(
        request: NotificationSettingsRequest,
        user_id: int = Depends(get_current_user_id)
):
    """사용자의 푸시 알림 수신 여부 및 시간을 업데이트합니다."""
    try:
        success = update_user_notification_settings(
            user_id,
            request.is_notification_enabled,
            request.notification_time
        )
        if not success:
            raise HTTPException(status_code=500, detail="알림 설정 업데이트에 실패했습니다.")

        return {
            "status": "success",
            "message": "알림 설정이 성공적으로 변경되었습니다.",
            "data": {
                "is_notification_enabled": request.is_notification_enabled,
                "notification_time": request.notification_time
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서버 에러: {str(e)}")


@router.patch("/fcm-token")
async def update_fcm_token_endpoint(
        request: FCMTokenRequest,
        user_id: int = Depends(get_current_user_id)
):
    """사용자의 기기 FCM 토큰을 갱신합니다."""
    try:
        success = update_user_fcm_token(user_id, request.fcm_token)
        if not success:
            raise HTTPException(status_code=500, detail="FCM 토큰 갱신에 실패했습니다.")

        return {
            "status": "success",
            "message": "FCM 토큰이 성공적으로 갱신되었습니다."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서버 에러: {str(e)}")