from playwright.async_api import async_playwright
import json
from urllib.parse import urlparse, parse_qs
from google import genai
import os
from dotenv import load_dotenv
import datetime
import pytz

import sys, os

# 다른 경로 파일 불러오기
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))

from dbController import save_db
from dbController import call_db

import yaml
from pathlib import Path

# 1. 파일 로드
CONFIG_PATH = Path(__file__).resolve().parent / "prompt_data.yaml"
with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# .env 파일의 환경 변수 로드
load_dotenv()

# 상위 경로 파일 불러오기
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
file_path = os.path.join(parent_dir, 'tag.json')

with open(file_path) as json_file:
    tag_data = json.load(json_file)

raw_prompt = config['prompts']['api_selector']

api_index = 1

# 사용자 요청 url을 받아 method에 따라 api = [method, api_url, header, payload] 배열을 반환하는 함수
# 유효한 api를 LLM API가 골라내도록 함
async def find_api(target_url):

    api = call_db.select_api(target_url)

    if api:
        return api

    site = call_db.select_site_id(target_url)
    if not site: #사이트가 없으면
        # 사이트 저장
        save_site(target_url)

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=False,
            # 프록시 설정 필요할 때 추가
            # proxy={"server": "http://192.168.49.1:8282"}
        )
        page = await browser.new_page()
        base_url = urlparse(target_url).netloc
        netloc = urlparse(target_url).netloc
        parts = netloc.split('.')
        domain_name = parts[-2] + '.' + parts[-1]  # 뒤에서 두 번째 요소 추출
        api = []

        # 네트워크 요청 가로채기 리스너
        async def capture_response(response):
            request = response.request
            method = request.method
            global api_index

            # # Content-Type 체크 방식 개선
            # content_type = response.headers.get("content-type", "").lower()

            # # 오타 버전(sciprt)과 표준 버전(script), 그리고 json을 모두 포괄
            # allowed_keywords = ["json", "script", "sciprt", "html"]

            # # 해당 키워드 중 하나라도 content-type에 포함되어 있는지 확인
            # if not any(keyword in content_type for keyword in allowed_keywords):
            #     return


            # Content-Type 체크 방식 수정
            # content_type = response.headers.get("content-type", "").lower()
            # allowed_types = ["application/json", "text/html", "text/javasciprt", "text/javascript"]
            # if not any(t in content_type for t in allowed_types):
            #     return
            #
            # # 불필요한 확장자 필터링 (논리 오류 수정)
            # trash_tuple = tuple(tag_data["trash_extensions"])
            # if request.url.lower().endswith(trash_tuple):
            #     return


            # 데이터 필터링 방식 전면 수정
            url = request.url
            content_type = response.headers.get("content-type", "").lower()

            print(f"들어오는 요청 Checking URL: {request.url}")
            print(f"DEBUG: URL={url} | Content-Type={content_type}")

            # 1. 전역 블랙리스트 체크 (광고/트래커는 데이터 증거가 있어도 차단)
            if any(trash in url for trash in tag_data["GLOBAL_TRASH_KEYWORDS"]):
                return

            # 2. [핵심] 강력한 데이터 징후 확인 (가장 먼저 수행)
            # URL에 '?'가 포함되어 있거나, DATA_INDICATORS(fo, joblist 등)가 하나라도 걸리면 무조건 통과
            has_data_evidence = '?' in url or any(ind in url for ind in tag_data["DATA_INDICATORS"])

            if not has_data_evidence:
                # 3. 징후가 없는 평범한 요청들만 '최소한'의 필터링 수행
                # Content-Type 체크 (오타 대응 포함)
                allowed_valid_types = ["json", "html", "script", "javas", "sciprt"]
                print(f"지금 들어온 content-type : {content_type}")
                if not any(k in content_type for k in allowed_valid_types):
                    return

                # 순수 정적 파일 체크 (이미지, 폰트 등 확실한 쓰레기만 쳐냄)
                # 징후가 없는 경우에만 확장자를 확인하므로, .fo API는 여기서 걸리지 않음
                if url.endswith(tuple(tag_data["trash_extensions"])):
                    return


            print(f"Checking URL: {request.url}")

            # --- 여기서부터 수집 로직 ---
            parsed_url = urlparse(request.url)
            url_params = parse_qs(parsed_url.query, keep_blank_values=True)
            full_payload = {k: v[0] for k, v in url_params.items()}  # 우선 URL 파라미터를 담음

            # 2. POST 바디 데이터 추가 추출 (POST/JSON 데이터)
            payload = request.post_data
            if payload:
                try:
                    # JSON 형태인 경우 기존 payload에 업데이트
                    json_data = json.loads(payload)
                    if isinstance(json_data, dict):
                        full_payload.update(json_data)
                except json.JSONDecodeError:
                    # 쿼리 스트링 형태의 Body인 경우 (application/x-www-form-urlencoded)
                    body_params = parse_qs(payload, keep_blank_values=True)
                    body_payload = {k: v[0] for k, v in body_params.items()}
                    full_payload.update(body_payload)

            # 6. 바디 데이터 가져오기
            body = ""
            try:
                if response.status == 200:
                    body = await response.text()
            except Exception as e:
                # 이미지나 바이너리 데이터일 경우 에러 발생 가능
                print(f"Body 읽기 실패 ({request.url}): {e}")
                return
            request_api = {
                "api_index": api_index,
                "method_type": method,
                "type": request.resource_type,  # fetch, xhr 등이 찍힘
                "api_url": request.url,
                "headers": request.headers,
                "payload": full_payload,
                "length": len(body),
                "sample": body[:300] if body else "",
            }
            api_index += 1
            print(f"API 수집 성공 -> [{method}] {request.url}")
            api.append(request_api)

        page.on("response", capture_response)

        try:
            await page.goto(target_url, wait_until="networkidle", timeout=30000)
        except:
            try:
                await page.goto(target_url, wait_until="load", timeout=30000)
            except:
                print("로딩 오류")

        await browser.close()

        print("api 리스트 : ", api)

        response_data = call_gemini_select_api(api)
        selected_index = int(response_data.get("index"))
        selected_api = next((item for item in api if item["api_index"] == selected_index), None)

        # 디버깅용
        if selected_api:
            final_url = selected_api["api_url"]  # 오타 없는 100% 원본 URL
            method = selected_api["method_type"]
            headers = selected_api["headers"]
            payload = selected_api["payload"]
            reason = response_data.get("reason")


        # api 저장
        save_api(selected_api, target_url)

        return selected_api



def call_gemini_select_api(api_list):
    # 3. Gemini 연결
    api_key = os.getenv("GEMINI_API_KEY_SELECT_API")
    client = genai.Client(api_key=api_key)

    prompt = f"""
당신은 범용 웹 크롤링 자동화 전문가입니다. 제공된 API 요청 리스트 중 해당 페이지의 **'핵심 메인 데이터(Primary Content Data)'**를 제공하는 API를 단 하나만 선별하세요.

[선별 가이드라인]
1. 목적성: 페이지 접속 시 사용자에게 즉시 보여지는 본문 데이터(공지 목록, 채용 공고, 메인 대시보드 정보 등)를 담고 있어야 함.
2. 제외 대상: 
   - 'log', 'collect', 'analytics', 'sentry', 'telemetry'가 포함된 분석용 API.
   - 'auth', 'login', 'token' 등 인증 관련 API.
   - 단순 이미지, CSS, JS 파일 요청.
3. 우선순위:
   - 범용성 : main과 같은 키워드를 우선으로 보되 특정 키워드(예: notice)에 현혹되지 말고, 실제 화면을 구성하는 '메인 컨텐츠'인지를 `sample` 구조로 판단함.
   - 응답의 형태가 JSON 배열([])이거나, 여러 데이터 그룹을 한 번에 가져오는 구조인 경우.
   - 쿼리 파라미터에 카테고리 분류(Category), 정렬(Sort), 그룹(Group) 관련 키가 포함된 경우.
   - 데이터 풍부성: `length`(길이)가 충분히 길고, `sample` 데이터 내에 리스트([]) 형태나 다양한 데이터 필드(`arcList`, `main` 등)가 포함된 것을 우선함.

[데이터 리스트] : {api_list}
api_url은 생성된 데이터 그대로 가져오세요.
결과는 반드시 아래 JSON 형식으로만 응답하세요:
{{
  "index": "선택한 api의 index"
  "reason": "이 API를 핵심 데이터로 판단한 이유 (짧게)"
}}
"""

    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        # 프롬프트 입력
        contents=prompt,
        config={'response_mime_type': 'application/json'}
    )
    print("gemini 호출 결과 : ", response.text)
    api_data = json.loads(response.text)
    return api_data

def save_site(url):

    save_db.insert_site(
        site_url=url,
        created_at=datetime.datetime.now(pytz.timezone('Asia/Seoul')).isoformat(),
    )
    print("신규 사이트 정보를 DB에 저장")


def save_api(api, url):

    site_id = call_db.select_site_id(url)
    print(api)

    save_db.insert_api(
        site_id=site_id,
        method_type=api.get("method_type"),
        api_url=api.get("api_url"),
        headers=api.get("headers"),
        payload=api.get("payload"),
        last_hash=None
    )
    print("신규 API 정보를 DB에 저장")

