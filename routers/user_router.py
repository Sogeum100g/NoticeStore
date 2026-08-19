from fastapi import APIRouter, HTTPException, Depends

# 💡 가칭 `delete_user_account`를 임포트 목록에 추가했습니다. 실제 구현하신 함수명으로 수정해 주세요.
from repositories.user_repo import (
    delete_device_fcm_token,
    update_user_nickname, 
    get_user_info_by_id, 
    update_user_notification_settings, 
    delete_user_account,
    upsert_device_fcm_token 
)
from schemas import FCMDeleteRequest, NicknameRequest, NotificationSettingsRequest, FCMTokenRequest

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
                "max_sites_limit": user_info["max_sites_limit"],
                "social_id": user_info.get("social_id"),
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

@router.post("/fcm-token")
async def register_fcm_token(
        request: FCMTokenRequest,
        user_id: int = Depends(get_current_user_id)
):
    """사용자의 기기별 FCM 토큰을 등록하거나 갱신하는 엔드포인트"""
    try:
        is_upserted = upsert_device_fcm_token(
            user_id=user_id,
            fcm_token=request.fcm_token,
            device_id=request.device_id,
            device_type=request.device_type
        )
        
        if not is_upserted:
            raise HTTPException(status_code=500, detail="기기 토큰 등록에 실패했습니다.")

        return {
            "status": "success",
            "message": "기기 토큰이 성공적으로 등록되었습니다.",
            "data": {
                "device_id": request.device_id,
                "device_type": request.device_type
            }
        }
    except Exception as e:
        print(f"❌ [서버 에러] register_fcm_token 실패: {e}")
        raise HTTPException(status_code=500, detail=f"서버 에러: {str(e)}")

@router.delete("/fcm-token")
async def delete_fcm_token(
    request: FCMDeleteRequest,
    user_id: int = Depends(get_current_user_id)
):
    """로그아웃 시 특정 기기의 FCM 토큰을 제거하는 엔드포인트"""
    try:
        # 삭제 성공 여부와 관계없이 요청이 도달했으므로 로직을 수행합니다.
        delete_device_fcm_token(user_id, request.device_id)
        
        return {
            "status": "success", 
            "message": "해당 기기의 알림 세션이 성공적으로 종료되었습니다."
        }
    except Exception as e:
        print(f"❌ [서버 에러] remove_fcm_token 실패: {e}")
        raise HTTPException(status_code=500, detail=f"서버 에러: {str(e)}")

@router.delete("/me")
async def delete_my_account(user_id: int = Depends(get_current_user_id)):
    """현재 로그인된 사용자의 계정을 삭제하는 엔드포인트"""
    try:
        success = delete_user_account(user_id)
        if not success:
            raise HTTPException(status_code=500, detail="회원탈퇴 처리에 실패했습니다.")

        return {
            "status": "success",
            "message": "회원탈퇴가 성공적으로 처리되었습니다."
        }
    except Exception as e:
        print(f"❌ [서버 에러] delete_my_account 실패: {e}")
        raise HTTPException(status_code=500, detail=f"서버 에러: {str(e)}")
