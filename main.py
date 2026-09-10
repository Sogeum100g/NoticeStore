import asyncio
import sys
import os
import uvicorn
from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from routers import (
    auth_router,
    user_router,
    folder_router,
    notice_router,
    subscription_router,
    inquiry_router,
    crawl_admin_router,
)

load_dotenv()

# 스케줄러 실행 코드를 제거하고 빈 lifespan 유지 (또는 lifespan 설정 자체를 제거해도 무방합니다)
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(
    title="공지저장소(NoticeStore) API",
    description="공지저장소의 통합 백엔드 시스템입니다.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(auth_router.router)
v1_router.include_router(user_router.router)
v1_router.include_router(folder_router.router)
v1_router.include_router(notice_router.router)
v1_router.include_router(subscription_router.router)
v1_router.include_router(inquiry_router.router)
v1_router.include_router(crawl_admin_router.router)

app.include_router(v1_router)

@app.get("/")
async def root():
    return {"message": "NoticeStore API is running smoothly!"}

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
