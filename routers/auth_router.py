import os
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, status
from dotenv import load_dotenv

# 구글 인증 라이브러리
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from repositories.user_repo import get_or_create_user, upsert_device_fcm_token
# 분리해둔 스키마 및 DB 함수 임포트
from schemas import LoginRequest



load_dotenv()

# 환경 변수 로드
GOOGLE_WEB_CLIENT_ID = os.getenv("GOOGLE_WEB_CLIENT_ID")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_DAYS = int(os.getenv("ACCESS_TOKEN_EXPIRE_DAYS", "7"))

router = APIRouter(prefix="/auth", tags=["Authentication"])

# --- [도움 함수: 토큰 검증 및 생성] ---

def verify_google_token(token: str):
    """구글 서버를 통해 idToken의 유효성을 검증합니다."""
    try:
        id_info = id_token.verify_oauth2_token(
            token, google_requests.Request(), GOOGLE_WEB_CLIENT_ID
        )
        return id_info
    except ValueError:
        # 유효하지 않은 토큰일 경우
        return None

def create_access_token(data: dict):
    """서버 자체 JWT 액세스 토큰을 생성합니다."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# --- [API 엔드포인트] ---

@router.post("/login")
async def social_login(request: LoginRequest):
    """
    구글 소셜 로그인을 처리하고, 기기별 FCM 토큰을 1:N 테이블에 등록합니다.
    """
    # 1. 구글 토큰 검증
    user_info = verify_google_token(request.access_token)
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 구글 토큰입니다."
        )

    email = user_info.get("email")
    social_id = user_info.get("sub")

    # 2. 사용자 조회 또는 생성 (계정 본연의 정보만 처리) [cite: 2026-03-10]
    user_data = get_or_create_user(
        email=email,
        social_id=social_id,
        provider=request.provider,
        referrer_code=request.referrer_code
    )

    if not user_data:
        raise HTTPException(
            status_code=500,
            detail="사용자 정보를 생성하거나 조회하는 데 실패했습니다."
        )

    # 3. 🚀 [핵심 추가] 기기별 FCM 토큰 등록 (1:N 구조 지원) [cite: 2026-03-10]
    # 클라이언트(Flutter)에서 보낸 device_id와 device_type을 사용합니다.
    if request.fcm_token and request.device_id:
        upsert_success = upsert_device_fcm_token(
            user_id=user_data["user_id"],
            fcm_token=request.fcm_token,
            device_id=request.device_id,
            device_type=request.device_type
        )
        if not upsert_success:
            # 토큰 등록 실패는 로그만 남기고 로그인은 진행할 수 있습니다.
            print(f"⚠️ [FCM] 유저 {user_data['user_id']}의 기기 등록 실패")

    # 4. 자체 서비스용 JWT 토큰 생성
    access_token = create_access_token(data={"sub": str(user_data["user_id"])})

    # 5. 전체 데이터 응답
    return {
        "status": "success",
        "access_token": access_token,
        "user": user_data 
    }