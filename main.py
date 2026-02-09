# main.py
import asyncio
import sys

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel #
from scrape.dbController.call_db import get_all_notices # 기존 DB 조회 함수 불러오기
from scrape.dataController.scrape_auto import run_full_scrape



# 1. 루프 정책 설정 함수화
def set_windows_policy():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


app = FastAPI()




@app.get("/")
def root():
    return {"message": "공지저장소 API 서버가 작동 중입니다!"}


@app.post("/register_site")
def register_site(request_data: dict):
    target_url = request_data.get("url")

    # 1. 먼저 DB에서 해당 URL의 공지가 하나라도 있는지 체크합니다.
    # (예시 함수: get_notice_count_by_url)
    # if check_if_notices_exist(target_url):
        # 이미 데이터가 있다면 스크래핑 없이 즉시 성공 응답
        # return {"status": "success", "message": "existing_data"}

    # 2. 데이터가 없을 때만 스크래핑 실행 (여기서 시간이 오래 걸림)
    # run_scraper_and_save(target_url)
    # return {"status": "success", "message": "new_data_scraped"}


@app.get("/notices")
def read_notices(url):
    raw_data = get_all_notices(url)
    # 리스트를 딕셔너리 형태로 변환하여 반환
    formatted_data = [
        {
            "notice_id": row[0],
            "title": row[1],
            "created_at": row[2],
            "url": row[3]
        } for row in raw_data
    ]
    return {"status": "success", "data": formatted_data}


# 2. 이 클래스 별도 선언
class SiteRequest(BaseModel):
    url: str


@app.post("/add-site")
async def add_new_site(request: SiteRequest):
    url = request.url
    print(f"현재 실행 루프: {type(asyncio.get_running_loop())}")

    # 여기서 비동기로 크롤링 함수를 호출하여 프로세스를 시작합니다.
    result = await run_full_scrape(url)

    return result


# 3. 직접 실행부 추가 (중요)
if __name__ == "__main__":
    set_windows_policy() # 여기서 다시 한번 루프 정책을 설정합니다.
    print(type(asyncio.get_event_loop()))
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False, loop="asyncio")