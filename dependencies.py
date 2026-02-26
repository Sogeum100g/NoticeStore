import os
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv

from repositories.user_repo import get_user_info_by_id

# DB 조회 함수 (사용자 역할 확인용)


load_dotenv()

# 보안 설정 로드
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")

# Bearer 토큰 스키마 설정
security = HTTPBearer()


def get_current_user_id(auth: HTTPAuthorizationCredentials = Depends(security)) -> int:
    """
    HTTP Header의 Authorization: Bearer <JWT>에서 토큰을 추출하고
    유효성을 검증한 뒤 user_id(sub)를 반환합니다.
    """
    token = auth.credentials
    try:
        # JWT 디코딩
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: str = payload.get("sub")

        if user_id_str is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="유효하지 않은 인증 토큰입니다. (sub 누락)"
            )
        return int(user_id_str)

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 토큰이 만료되었습니다."
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 인증 토큰입니다."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"인증 처리 중 서버 오류 발생: {str(e)}"
        )


def require_admin(user_id: int = Depends(get_current_user_id)) -> int:
    """
    현재 로그인한 사용자가 관리자(ADMIN)인지 확인합니다.
    """
    user_info = get_user_info_by_id(user_id)

    # 디버깅을 위한 로그 출력
    print(f"--- [AUTH DEBUG] ---")
    print(f"User ID from Token: {user_id}")
    print(f"User Info from DB: {user_info}")
    print(f"---------------------")

    if not user_info or user_info.get('role') != 'ADMIN':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다."
        )
    return user_id