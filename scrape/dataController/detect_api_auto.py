import os
import sys
import json
import logging
import datetime
from typing import Optional
import pytz
import yaml
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.async_api import async_playwright
from google import genai
from google.genai import types
from dotenv import load_dotenv

# 상위 경로를 시스템 패스에 추가하여 repositories 폴더를 인식할 수 있게 합니다.
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))

# 기존 call_db, save_db 대신 통합된 notice_repo를 불러옵니다.
from repositories import notice_repo

# -----------------------------------------------------------------------------
# 로깅 설정 (print 대체)
# 운영 서버에서는 INFO 이상만 남겨 로그 폭발을 방지합니다.
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

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
async def find_api(target_url):

    logger.info(f"🚀 [find_api 시작] 타겟 URL: {target_url}")

    api = notice_repo.select_api(target_url)

    if api:
        return api

    # 2. 사이트 정보가 없다면 새로 생성하고 ID를 반환받습니다.
    # 주의: save_site 함수가 내부적으로 insert_site를 호출한다면, 
    # insert_site처럼 데이터베이스에서 생성된 site_id를 return하도록 구현되어 있어야 합니다.
    logger.info("🔍 [DB 조회] 저장된 API가 없습니다. 신규 사이트 등록 및 분석을 시작합니다.")
    site_id = notice_repo.select_site_id(target_url)
    if not site_id:
        site_id = save_site(target_url)

        
    if not site_id:
        logger.error(f"사이트 ID 확보 실패: {target_url}")
        return None

    async with async_playwright() as p:
        
        # 서버(CLI) 환경에서 브라우저가 죽지 않도록 headless=True 설정
        try:
            browser = await p.chromium.launch(
                headless=True,
                # proxy={"server": "http://192.168.49.1:8282"},
            )
            page = await browser.new_page()
        except Exception as e:
            logger.error(f"❌ 브라우저 초기화 실패: {e}", exc_info=True)
            return None


        api = []

        # 네트워크 요청 가로채기 리스너
        async def capture_response(response):
            request = response.request
            method = request.method
            global api_index

            if method == "OPTIONS":
                return

            # -----------------------------------------------------------------
            # [Step 1] 명백한 리소스 타입 차단 (Playwright 기본 기능)
            # -----------------------------------------------------------------
            # document, fetch, xhr 등 통신/문서 관련 타입만 남기고 시각적 요소는 즉시 버림
            if request.resource_type in ['image', 'stylesheet', 'media', 'font', 'websocket']:
                return

            # -----------------------------------------------------------------
            # [Step 2] 확장자 및 블랙리스트 차단 (순수 경로 기준)
            # -----------------------------------------------------------------
            parsed_req_url = urlparse(request.url)
            req_path = parsed_req_url.path.lower()

            # 💡 주의: tag.json의 trash_extensions에 '.fo', '.do'가 있다면 반드시 삭제!
            # 쿼리스트링(?v=1.0 등)을 뗀 순수 파일명이 js, css 등으로 끝나면 무조건 버림
            trash_exts = ('.js', '.mjs', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2')
            if req_path.endswith(trash_exts):
                return

            # 구글 애널리틱스, 페이스북 픽셀 등 전역 블랙리스트 차단
            if any(trash in request.url for trash in tag_data.get("GLOBAL_TRASH_KEYWORDS", [])):
                return

            # -----------------------------------------------------------------
            # [Step 3] 바디 데이터 추출 및 최소한의 데이터 징후 확인
            # -----------------------------------------------------------------
            # 여기까지 통과했다면 도메인이 완전히 다르더라도 (예: 타사 SaaS API, 외부 DB 연동 등) 모두 수집 대상!
            
            body = ""
            try:
                if response.status == 200:
                    # 응답 헤더의 Content-Length 또는 실제 텍스트 길이를 확인
                    content_length = response.headers.get('content-length')
                    if content_length and int(content_length) < 100:
                        # 100바이트 이하의 응답은 유의미한 리스트 데이터일 확률이 0에 가깝습니다.
                        return 
                    
                    body = await response.text()
            except Exception:
                pass # 바디를 못 읽어도(바이너리 등) 에러 내지 않고 빈 값으로 둠

            # 만약 바디 데이터가 있고, 그 시작이 명확한 데이터 구조({, [, <)가 아니면 버림
            # (쓸데없는 평문 텍스트 로그나 이상한 포맷을 쳐내기 위한 아주 느슨한 최후의 보루)
            if body:
                snippet = body[:50].strip()
                if not (snippet.startswith("{") or snippet.startswith("[") or snippet.startswith("<")):
                    return

            # -----------------------------------------------------------------
            # [Step 4] 유효 데이터 메타데이터 조립 (기존과 동일)
            # -----------------------------------------------------------------
            url_params = parse_qs(parsed_req_url.query, keep_blank_values=True)
            full_payload = {k: v[0] for k, v in url_params.items()}

            payload = None
            try:
                # 💡 수정된 부분: 바이너리 데이터 디코딩 시 발생하는 에러를 방어합니다.
                payload = request.post_data
            except Exception:
                # 압축 데이터(0x8b)나 파일 등 텍스트로 읽을 수 없는 payload는 생략합니다.
                pass
            
            if payload:
                try:
                    json_data = json.loads(payload)
                    if isinstance(json_data, dict):
                        full_payload.update(json_data)
                except json.JSONDecodeError:
                    body_params = parse_qs(payload, keep_blank_values=True)
                    full_payload.update({k: v[0] for k, v in body_params.items()})

            request_api = {
                "api_index": api_index,
                "method_type": method,
                "type": request.resource_type,
                "api_url": request.url,
                "headers": request.headers,
                "payload": full_payload,
                "length": len(body),
                "sample": body[:300] if body else "",
            }
            api_index += 1
            print(f"✅ 후보 수집 -> [{method}] {request.url}")
            api.append(request_api)

        page.on("response", capture_response)

        # 💡 문제의 페이지 접속 구간 집중 로깅
        try:
            await page.goto(target_url, wait_until="networkidle", timeout=30000)
            logger.info("✅ [1차 접속 성공] 페이지 렌더링 및 네트워크 안정화 완료")
        except Exception as e:
            try:
                await page.goto(target_url, wait_until="load", timeout=30000)
                logger.info("✅ [2차 접속 성공] load 이벤트 기반 접속 완료")
            except Exception as e2:
                # 💡 exc_info=True 옵션을 주어 어디서 터졌는지 스택 트레이스를 끝까지 추적합니다.
                logger.error(f"❌ [치명적 에러] 페이지 로딩 최종 실패: {target_url}", exc_info=True)

        await browser.close()

        logger.info(f"수집된 API 후보 개수: {len(api)}")

        if not api:
            logger.warning("수집된 API 후보가 없습니다.")
            return None

        # 🚀 최적화 핵심: LLM 전달용 경량화 리스트 생성
        llm_optimized_list = []
        for item in api:
            # 판단에 불필요한 headers, payload, type은 제외하고 URL과 핵심 샘플만 전달
            optimized_item = {
                "api_index": item["api_index"],
                "method_type": item["method_type"],
                "api_url": item["api_url"],
                # 샘플 텍스트의 불필요한 공백과 줄바꿈을 제거하여 토큰 압축
                "sample": item["sample"].replace('\n', '').replace('\r', '').strip()[:150] if item["sample"] else ""
            }
            llm_optimized_list.append(optimized_item)

        # LLM을 통한 최종 API 선정
        logger.info("🤖 [LLM 호출] Gemini를 이용한 핵심 API 선별 작업 시작")
        # 원본 api가 아닌 llm_optimized_list를 전달합니다.
        response_data = call_gemini_select_api(llm_optimized_list)

        if not response_data:
            logger.error("❌ Gemini API 호출에서 응답을 받지 못했습니다.")
            return None
        
        try:
            selected_index = int(response_data.get("index"))
            if selected_index == -1:
                logger.warning("LLM이 유효한 API를 찾지 못했습니다. (index: -1)")
                return None
                
            selected_api = next((item for item in api if item["api_index"] == selected_index), None)
        except (ValueError, TypeError):
            logger.error("Gemini API의 응답에서 유효한 index를 찾지 못했습니다.")
            selected_api = None

        if selected_api:
            logger.info(f"최종 선택된 API: {selected_api['api_url']}")
            save_api(selected_api, target_url)
            
            # 3. 새로 찾은 API 딕셔너리에 확보해둔 site_id를 수동으로 추가해서 반환합니다.
            selected_api['site_id'] = site_id

        return selected_api

def call_gemini_select_api(api_list):
    api_key = os.getenv("GEMINI_API_KEY_SELECT_API")
    client = genai.Client(api_key=api_key)

    # 1. 페이로드 극한 압축 (공백 및 줄바꿈 제거)
    # Python 리스트를 그대로 넣으면 띄어쓰기가 포함되어 토큰이 낭비됩니다.
    # separators=(',', ':')를 통해 불필요한 공백을 완전히 제거한 순수 텍스트로 직렬화합니다.
    compact_api_data = json.dumps(api_list, ensure_ascii=False, separators=(',', ':'))
    
    prompt = raw_prompt.format(api_list=compact_api_data)

    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            # 2. 결정론적 응답 유도
            # 분류 및 선택 작업이므로 창의성을 0으로 낮춰 정확도를 극대화합니다.
            temperature=0.0,
            # 3. 응답 스키마(Schema) 강제
            # LLM이 반드시 이 형태의 JSON만 반환하도록 API 단에서 통제합니다.
            response_schema=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "index": types.Schema(
                        type=types.Type.INTEGER,
                        description="선택한 API의 api_index"
                    ),
                    "reason": types.Schema(
                        type=types.Type.STRING,
                        description="이 API를 핵심 데이터로 판단한 명확한 근거"
                    ),
                },
                required=["index", "reason"]
            )
        )
    )
    
    # ---------------------------------------------------------
    # ✅ [업데이트] Gemini 2.5 Flash Lite 비용 계산 로깅
    # ---------------------------------------------------------
    usage = response.usage_metadata
    in_tokens = usage.prompt_token_count
    out_tokens = usage.candidates_token_count
    
    # 단가 설정 (1M 토큰당 입력 $0.075 / 출력 $0.30, 환율 1,350원 기준)
    cost_in = (in_tokens / 1_000_000) * 0.075 * 1350
    cost_out = (out_tokens / 1_000_000) * 0.30 * 1350
    total_krw = cost_in + cost_out

    logger.info(f"Gemini API 호출 완료 (입력 데이터 개수: {len(api_list)})")
    logger.info(
        f"📊 [Gemini 2.5 Flash Lite] API Selection | "
        f"Tokens: (In:{in_tokens} / Out:{out_tokens}) | "
        f"Cost: ₩{total_krw:.4f}"
    )
    # ---------------------------------------------------------
    
    api_data = json.loads(response.text)
    return api_data


def save_site(url):
    # 💡 insert_site가 반환하는 site_id를 변수에 담습니다.
    site_id = notice_repo.insert_site(
        site_url=url,
        created_at=datetime.datetime.now(pytz.timezone('Asia/Seoul'))
    )
    
    logger.info(f"신규 사이트 정보 DB 저장 완료 (ID: {site_id}): {url}")
    
    # 💡 상위 함수(find_api -> run_full_scrape)로 이 ID를 돌려줍니다.
    return site_id


def save_api(api, url):
    site_id = notice_repo.select_site_id(url)

    notice_repo.insert_api(
        site_id=site_id,
        method_type=api.get("method_type"),
        api_url=api.get("api_url"),
        headers=api.get("headers"),
        payload=api.get("payload"),
        last_hash=None
    )
    logger.info("신규 API 정보 DB 저장 완료")