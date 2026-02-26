import asyncio
import sys
import os
import uvicorn
from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from contextlib import asynccontextmanager

# 서비스 및 스케줄러 로직 임포트
from services.scheduler_service import start_scheduler, stop_scheduler

# 우리가 리팩토링한 라우터들 임포트
from routers import (
    auth_router,
    user_router,
    folder_router,
    notice_router,
    subscription_router,
    inquiry_router
)

# .env 로드
load_dotenv()


# 서버 생명주기 관리 (스케줄러 시작/종료)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버 시작 시 스케줄러 가동 (크롤링 및 알림)
    # start_scheduler()
    yield
    # 서버 종료 시 스케줄러 안전하게 중단
    # stop_scheduler()


app = FastAPI(
    title="공지저장소(NoticeStore) API",
    description="공지저장소의 통합 백엔드 시스템입니다.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# --- [API 라우터 등록] ---
# 모든 API를 v1 버전으로 묶어서 관리합니다. [cite: 2025-10-01]
v1_router = APIRouter(prefix="/v1")

v1_router.include_router(auth_router.router)
v1_router.include_router(user_router.router)
v1_router.include_router(folder_router.router)
v1_router.include_router(notice_router.router)
v1_router.include_router(subscription_router.router)
v1_router.include_router(inquiry_router.router)

# 최종적으로 앱에 v1 라우터 포함
app.include_router(v1_router)


@app.get("/")
async def root():
    return {"message": "NoticeStore API is running smoothly!"}


if __name__ == "__main__":
    # Windows 환경을 위한 이벤트 루프 정책 설정
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)