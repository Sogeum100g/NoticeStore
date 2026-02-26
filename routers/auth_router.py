import os
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, status
from dotenv import load_dotenv

# 구글 인증 라이브러리
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from repositories.user_repo import get_or_create_user
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
    구글 소셜 로그인을 처리하고 JWT 토큰을 발급합니다.
    신규 유저일 경우 자동으로 회원가입 처리(get_or_create_user)를 수행합니다.
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

    # 2. DB에서 사용자 확인 또는 생성
    # [cite: 2026-02-20] 로직 반영: 닉네임 유무에 따른 튜플 처리
    user_data = get_or_create_user(
        email=email,
        social_id=social_id,
        provider=request.provider,
        fcm_token=request.fcm_token
    )

    if isinstance(user_data, tuple):
        user_id, nickname = user_data
    else:
        user_id = user_data
        nickname = None  # 신규 유저이거나 닉네임 정보가 없는 경우

    # 3. 자체 서비스용 JWT 토큰 생성
    access_token = create_access_token(data={"sub": str(user_id)})

    return {
        "status": "success",
        "access_token": access_token,
        "user": {
            "user_id": user_id,
            "email": email,
            "nickname": nickname,
            "provider": request.provider
        }
    }