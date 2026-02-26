from playwright.async_api import async_playwright
import json
from urllib.parse import urlparse, parse_qs
from google import genai
import os
from dotenv import load_dotenv
import datetime
import pytz

import sys, os
from pathlib import Path
import yaml

# 상위 경로를 시스템 패스에 추가하여 repositories 폴더를 인식할 수 있게 합니다.
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))

# 💡 수정: 기존 call_db, save_db 대신 통합된 notice_repo를 불러옵니다.
from repositories import notice_repo

# 1. 파일 로드
CONFIG_PATH = Path(__file__).resolve().parent / "prompt_data.yaml"
with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# 전역 변수로 프롬프트 원형(Template) 저장
raw_prompt = config['prompts']['api_selector']

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
    # 💡 수정: notice_repo 사용
    api = notice_repo.select_api(target_url)

    if api:
        return api

    # 💡 수정: notice_repo 사용
    site = notice_repo.select_site_id(target_url)
    if not site:  # 사이트가 없으면
        # 사이트 저장
        save_site(target_url)

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=False,
            # 프록시 설정 필요할 때 추가
            # proxy={"server": "http://192.168.49.1:8282"},
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

            # 데이터 필터링 방식 전면 수정
            url = request.url
            content_type = response.headers.get("content-type", "").lower()

            print(f"들어오는 요청 Checking URL: {request.url}")
            print(f"DEBUG: URL={url} | Content-Type={content_type}")

            # 1. 전역 블랙리스트 (광고 등) - 최우선
            if any(trash in url for trash in tag_data["GLOBAL_TRASH_KEYWORDS"]):
                return

            # 2. 확장자 체크를 징후 검사보다 위로 올림
            if url.endswith(tuple(tag_data["trash_extensions"])):
                return

            # 3. 그 다음 데이터 징후 확인
            has_data_evidence = '?' in url or any(ind in url for ind in tag_data["DATA_INDICATORS"])

            if not has_data_evidence:
                # 웹사이트 구동용 스크립트 쳐내기
                if url.endswith('.js'):
                    static_code_keywords = ["webpack", "framework-", "app-", "polyfills-", "runtime-", "vendor-"]
                    if any(lib in url for lib in static_code_keywords):
                        return

                # 4. 마지막 관문: Content-Type 체크
                allowed_valid_types = ["json", "html", "script", "javas", "sciprt"]
                if not any(k in content_type for k in allowed_valid_types):
                    return

            print(f"Checking URL: {request.url}")

            # --- 여기서부터 수집 로직 ---
            parsed_url = urlparse(request.url)
            url_params = parse_qs(parsed_url.query, keep_blank_values=True)
            full_payload = {k: v[0] for k, v in url_params.items()}

            # 2. POST 바디 데이터 추가 추출 (POST/JSON 데이터)
            payload = request.post_data
            if payload:
                try:
                    json_data = json.loads(payload)
                    if isinstance(json_data, dict):
                        full_payload.update(json_data)
                except json.JSONDecodeError:
                    body_params = parse_qs(payload, keep_blank_values=True)
                    body_payload = {k: v[0] for k, v in body_params.items()}
                    full_payload.update(body_payload)

            # 6. 바디 데이터 가져오기
            body = ""
            try:
                if response.status == 200:
                    body = await response.text()
            except Exception as e:
                print(f"Body 읽기 실패 ({request.url}): {e}")
                return

            request_api = {
                "api_index": api_index,
                "method_type": method,
                "type": request.resource_type,
                "api_url": request.url,
                "headers": request.headers,
                "payload": full_payload,
                "length": len(body),
                "sample": body[:300] if body else "",
                "full_body": body,
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
        print("gemini api 리스트 입력 토큰 개수 : ", len(api))

        response_data = call_gemini_select_api(api)
        selected_index = int(response_data.get("index"))
        selected_api = next((item for item in api if item["api_index"] == selected_index), None)

        if selected_api:
            final_url = selected_api["api_url"]
            method = selected_api["method_type"]
            headers = selected_api["headers"]
            payload = selected_api["payload"]
            reason = response_data.get("reason")
            full_body = selected_api["full_body"]
            print("full_body : ", full_body, " -> full_body")

        # api 저장
        save_api(selected_api, target_url)

        return selected_api


def call_gemini_select_api(api_list):
    # 3. Gemini 연결
    api_key = os.getenv("GEMINI_API_KEY_SELECT_API")
    client = genai.Client(api_key=api_key)

    # 💡 핵심 수정: YAML에서 불러온 문자열에 파이썬 .format()을 사용해 데이터 주입
    prompt = raw_prompt.format(api_list=api_list)

    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=prompt,
        config={'response_mime_type': 'application/json'}
    )
    print("gemini 입력 토큰 개수 : ", len(api_list))
    print("gemini 호출 결과 : ", response.text)
    api_data = json.loads(response.text)
    return api_data


def save_site(url):
    # 💡 수정: notice_repo 사용 및 파이썬 datetime 객체 직접 전달
    notice_repo.insert_site(
        site_url=url,
        created_at=datetime.datetime.now(pytz.timezone('Asia/Seoul'))
    )
    print("신규 사이트 정보를 DB에 저장")


def save_api(api, url):
    # 💡 수정: notice_repo 사용
    site_id = notice_repo.select_site_id(url)
    print(api)

    notice_repo.insert_api(
        site_id=site_id,
        method_type=api.get("method_type"),
        api_url=api.get("api_url"),
        headers=api.get("headers"),
        payload=api.get("payload"),
        last_hash=None
    )
    print("신규 API 정보를 DB에 저장")