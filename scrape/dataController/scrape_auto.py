import asyncio
from urllib import robotparser
from urllib.parse import urlparse, parse_qs, unquote
import requests
import re
from bs4 import BeautifulSoup, Comment
import json
import sys, os
from dotenv import load_dotenv
from google import genai
import datetime
import pytz
import hashlib
import yaml
from pathlib import Path

# 다른 경로 파일 불러오기
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))

# 💡 수정: 통합된 notice_repo 임포트
from repositories import notice_repo
from dataController.detect_api_auto import find_api

current_data = ""
clean_data = ""

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

raw_prompt = config['prompts']['json_parser']


# Next.js의 표준 데이터 태그를 찾습니다.
def extract_next_data(soup):
    script_tag = soup.find('script', id='__NEXT_DATA__')
    if script_tag:
        data = json.loads(script_tag.string)
        return data
    return None


def remove_json_nulls(obj):
    if isinstance(obj, dict):
        return {
            k: remove_json_nulls(v)
            for k, v in obj.items()
            if v is not None
        }
    elif isinstance(obj, list):
        return [remove_json_nulls(item) for item in obj]
    else:
        return obj


def preprocessing(soup):
    """HTML DOM에서 무의미한 태그 및 주석을 제거하고 정제된 텍스트만 반환한다."""
    for element in soup.find_all(tag_data["trash_tags"]):
        element.decompose()

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    clean_text = soup.get_text(separator='\n', strip=True)
    return clean_text


raw_processing_prompt = config['prompts']['data_processing']

def data_processing(raw_data, target_url):
    now = datetime.datetime.now(pytz.timezone('Asia/Seoul'))
    current_time_iso = now.isoformat()

    # 💡 수정: notice_repo 사용
    site_id = notice_repo.select_site_id(target_url)

    # 💡 YAML 템플릿에 변수 주입
    # 참고: target_url은 프롬프트 지시사항 3번에 언급되어 있으나
    # {target_url} 형태의 placeholder가 텍스트 내부에 없다면 format 인자에서 생략 가능합니다.
    prompt = raw_processing_prompt.format(
        current_time_iso=current_time_iso,
        raw_data=raw_data
    )

    # Gemini 연결
    api_key = os.getenv("GEMINI_API_KEY_DATA_PROCESSING")
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=prompt,
        config={'response_mime_type': 'application/json'}
    )

    result = json.loads(response.text)
    result['site_id'] = site_id

    # 결과 내의 모든 url을 urljoin으로 보정
    for notice in result.get("notices", []):
        original_url = notice.get("url")
        if original_url:
            notice["url"] = target_url

    print(type(result))
    return result


def get_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def expand_url(short_url):
    """단축 URL 추적 및 브릿지 파싱"""
    try:
        response = requests.head(short_url, allow_redirects=True, timeout=5)
        expanded_url = response.url
        parsed_url = urlparse(expanded_url)

        if 'link.naver.com' in parsed_url.netloc:
            query_params = parse_qs(parsed_url.query)
            if 'url' in query_params:
                clean_url = unquote(query_params['url'][0])
                print(f"🔗 브릿지 파싱 완료: {clean_url}")
                return clean_url

        return expanded_url
    except requests.RequestException as e:
        print(f"❌ URL 전개 실패: {e}")
        return short_url


def process_notice_request(input_url):
    final_url = expand_url(input_url)
    return get_recent_info(final_url)


def get_recent_info(url):
    print("DB에서 기존 데이터 조회하여 반환")
    url = expand_url(url)
    print("복원시킨 url : ", url)

    # 💡 수정: notice_repo 사용
    raw_data = notice_repo.get_all_notices(url)
    site_id = notice_repo.select_site_id(url)

    formatted_notices = []
    for row in raw_data:
        formatted_notices.append({
            "notice_id": row[0],
            "title": row[1],
            "author": row[2] or "",
            "url": row[3],
            "content_preview": row[4] or "",
            "created_at": row[5].isoformat() if row[5] else "",
            "scraped_at": row[6].isoformat() if row[6] else "",
        })

    print("notices : ", formatted_notices)
    return {"status": "success", "site_id": site_id, "notices": formatted_notices}


async def is_crawling_allowed(url, user_agent='*'):
    print("robots.txt를 확인")
    parsed_url = urlparse(url)
    robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"
    print(robots_url)

    rp = robotparser.RobotFileParser()
    try:
        rp.set_url(robots_url)
        await asyncio.to_thread(rp.read)
    except Exception as e:
        print(f"robots.txt를 읽을 수 없거나 없습니다 (기본 허용): {e}")
        return True

    return rp.can_fetch(user_agent, url)


# 1. 공통 저장 로직을 함수로 분리
def sync_notices_to_db(site_id, notices, new_hash, api_url):
    # [1단계] 크롤링된 1페이지의 최신 공지사항 저장 (Upsert)
    for notice in notices:
        # 💡 수정: notice_repo.insert_or_update_notice 사용
        notice_repo.insert_or_update_notice(
            site_id=site_id,
            title=notice.get("title"),
            author=notice.get("author"),
            url=notice.get("url"),
            content_preview=notice.get("content_preview"),
            created_at=notice.get("created_at"),
            scraped_at=notice.get("scraped_at"),
            is_active=True
        )

    # [2단계] 수명이 다한 오래된 공지 일괄 정리 (Cleanup)
    # 💡 수정: notice_repo 사용
    notice_repo.deactivate_old_notices(site_id)

    # [3단계] 마지막 해시값 업데이트
    # 💡 수정: notice_repo 사용
    notice_repo.update_api(api_url=api_url, last_hash=new_hash)


def clean_html_text(raw_data):
    clean = re.sub(r'["\']?\w+["\']?\s*[:=]\s*(null|none|nan|undefined),?', '', raw_data, flags=re.IGNORECASE)
    clean = re.sub(r',+', ',', clean)
    return clean.replace(",}", "}").replace(",]", "]").strip()


async def run_full_scrape(url: str):
    global current_data
    url = expand_url(url)

    # 1. API 정보 로드
    api = await find_api(url)
    api_url = api.get('api_url')
    method_type = api.get('method_type')
    headers = api.get('headers', {})
    payload = api.get('payload')

    user_agent = headers.get('user-agent')

    # 2. robots.txt 체크
    allowed = await is_crawling_allowed(url, user_agent)
    if not allowed:
        print(f"⚠[차단] robots.txt 설정에 의해 크롤링이 금지된 URL입니다: {url}")
        return {"status": "blocked_by_robots.txt"}

    # 3. HTTP 요청 수행
    session = requests.Session()
    session.get(url, headers=headers)

    is_json = headers.get('content-type') == 'application/json'
    if method_type == 'GET':
        response = session.get(api_url, headers=headers)
    else:
        response = session.post(api_url, json=payload if is_json else None, data=None if is_json else payload,
                                headers=headers)

    response.encoding = response.apparent_encoding

    if not (200 <= response.status_code < 300):
        print(f"❌ 요청 실패: {response.status_code}")
        return {"status": "error", "notices": []}

    await asyncio.sleep(2)
    soup = BeautifulSoup(response.text, 'lxml')

    # 💡 수정: notice_repo 사용
    site_id = notice_repo.select_site_id(url)
    last_hash = notice_repo.select_last_hash(api_url)

    # 4. 데이터 추출 분기
    next_data = extract_next_data(soup)

    if next_data:
        cleaned_json = remove_json_nulls(next_data)
        clean_text = json.dumps(cleaned_json, ensure_ascii=False)
        new_hash = get_text_hash(clean_text)

        if new_hash != last_hash:
            print("🔄 [변경 감지] JSON 데이터 동기화 시작")
            clean_data = data_processing(clean_text, url)
            sync_notices_to_db(site_id, clean_data.get("notices", []), new_hash, api_url)
            return clean_data
    else:
        raw_text = soup.get_text(separator='\n', strip=True)
        clean_text = clean_html_text(raw_text)
        new_hash = get_text_hash(clean_text)

        if new_hash != last_hash:
            print("🤖 [변경 감지] LLM 기반 데이터 정제 시작")
            clean_data = data_processing(clean_text, url)

            if clean_data.get('notices') and clean_data['notices'][0]['title'] == "권한이 없거나 정보를 가져올 수 없습니다.":
                print("♻️ [2차 시도] 파서 변경 후 재시도")
                soup = BeautifulSoup(response.text, 'html.parser')
                raw_text = soup.get_text(separator='\n', strip=True)
                clean_text = clean_html_text(raw_text)
                clean_data = data_processing(clean_text, url)

            if clean_data.get('notices'):
                sync_notices_to_db(site_id, clean_data.get("notices", []), new_hash, api_url)
                print("clean_data : ", clean_data)
                return clean_data

    # 5. 변동 사항이 없을 경우
    print(f"✅ [유지] 데이터 변동 없음 ({url})")
    return get_recent_info(url)