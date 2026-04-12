import asyncio
from urllib import robotparser
from urllib.parse import urlparse, parse_qs, unquote, urljoin
import requests
import re
from bs4 import BeautifulSoup, Comment
import json
import sys, os
from dotenv import load_dotenv
from google import genai
from google.genai import types
import datetime
import pytz
import hashlib
import yaml
from pathlib import Path
import logging

# -----------------------------------------------------------------------------
# 로깅 설정 
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# 다른 경로 파일 불러오기
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))

from repositories import notice_repo
from dataController.detect_api_auto import find_api

current_data = ""
clean_data = ""

# 1. 파일 및 환경 변수 로드
CONFIG_PATH = Path(__file__).resolve().parent / "prompt_data.yaml"
with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

load_dotenv()

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
file_path = os.path.join(parent_dir, 'tag.json')

with open(file_path) as json_file:
    tag_data = json.load(json_file)

# 통합된 단일 프롬프트 로드
raw_processing_prompt = config['prompts']['data_processing']


def extract_next_data(soup):
    """Next.js의 표준 데이터 태그를 찾습니다."""
    script_tag = soup.find('script', id='__NEXT_DATA__')
    if script_tag:
        try:
            return json.loads(script_tag.string)
        except json.JSONDecodeError:
            return None
    return None

def determine_created_at(time_str, text_content):
    """
    유튜브의 상대 시간을 분석하여 정규화된 ISO 날짜를 반환합니다.
    (수정됨) 텍스트를 방어하고, 일 단위 이상은 시간을 자정으로 고정합니다.
    """
    now = datetime.datetime.now(pytz.timezone('Asia/Seoul'))
    current_year = now.year

    # 1. [우선순위 1] 본문 내 절대 날짜 추출 (예: 2026.3.11)
    match_a = re.search(r'(20\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})', text_content)
    if match_a:
        y, m, d = match_a.groups()
        return f"{y}-{int(m):02d}-{int(d):02d}T00:00:00+09:00"

    # 2. [우선순위 2] 상대 시간 텍스트 분석 (이미지 기반 케이스 처리)
    if not time_str:
        return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    # 숫자만 추출 (예: "5개월 전(수정됨)" -> 5)
    numbers = [int(s) for s in re.findall(r'\d+', time_str)]
    num = numbers[0] if numbers else 0
    
    delta = datetime.timedelta()
    is_long_term = False # 일 단위 이상인지 여부

    if "분" in time_str:
        delta = datetime.timedelta(minutes=num)
    elif "시간" in time_str:
        delta = datetime.timedelta(hours=num)
    elif "일" in time_str:
        delta = datetime.timedelta(days=num)
        is_long_term = True
    elif "주" in time_str:
        delta = datetime.timedelta(weeks=num)
        is_long_term = True
    elif "개월" in time_str:
        delta = datetime.timedelta(days=num * 30)
        is_long_term = True
    elif "년" in time_str:
        delta = datetime.timedelta(days=num * 365)
        is_long_term = True
    else:
        # "방금 전" 등 숫자가 없는 경우
        return now.isoformat()

    past_time = now - delta

    # 💡 [정규화 핵심] 
    # '3일 전', '5개월 전' 같은 데이터를 '03:16:15'처럼 저장하면 
    # 크롤링 시각에 따라 분/초가 계속 변해 데이터가 지저분해 보입니다.
    if is_long_term:
        # 일 단위 이상은 무조건 해당 날짜의 00:00:00으로 고정
        past_time = past_time.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        # 분/시간 단위는 현재 시각의 '분/초'만 제거하여 '시' 단위까지만 가독성 유지
        past_time = past_time.replace(minute=0, second=0, microsecond=0)

    return past_time.strftime('%Y-%m-%dT%H:%M:%S+09:00')


# 2. 유튜브 데이터 파서 (날짜 함수를 호출하여 사용)
def parse_youtube_community_data(yt_data, target_url):
    """
    ytInitialData에서 게시글을 추출합니다. (날짜 처리는 외부 함수에 위임)
    """
    notices = []
    now = datetime.datetime.now(pytz.timezone('Asia/Seoul'))
    current_time_iso = now.isoformat()

    # 내부 헬퍼: 게시글 본체 찾는 제너레이터
    def find_posts(obj):
        if isinstance(obj, dict):
            if 'backstagePostRenderer' in obj:
                yield obj['backstagePostRenderer']
            for v in obj.values():
                yield from find_posts(v)
        elif isinstance(obj, list):
            for item in obj:
                yield from find_posts(item)

    # 데이터 추출 루프
    for post in find_posts(yt_data):
        try:
            content_runs = post.get('contentText', {}).get('runs', [])
            full_text = "".join([run.get('text', '') for run in content_runs]).strip()
            
            if not full_text: continue

            # 작성자 및 URL 조합
            author = post.get('authorText', {}).get('runs', [{}])[0].get('text', '')
            post_id = post.get('postId')
            url = f"https://www.youtube.com/post/{post_id}" if post_id else target_url

            # 시간 정보 추출
            time_runs = post.get('publishedTimeText', {}).get('runs', [])
            raw_time = time_runs[0].get('text', '') if time_runs else ""
            
            # 💡 [핵심] 외부로 뺀 전역 함수를 호출합니다.
            created_at = determine_created_at(raw_time, full_text)

            notices.append({
                "title": full_text,
                "author": author,
                "created_at": created_at,
                "scraped_at": current_time_iso,
                "url": url
            })
        except Exception as e:
            continue

    return notices

def extract_yt_data(soup):
    """유튜브 특유의 ytInitialData 스크립트에서 JSON을 추출합니다."""
    import re
    import json
    
    # 1. ytInitialData 변수를 포함한 스크립트 태그 검색
    script_tag = soup.find("script", string=re.compile(r'var ytInitialData ='))
    if script_tag:
        try:
            # 2. 정규표현식으로 JSON 문자열만 추출
            json_text = re.search(r'var ytInitialData = (\{.*?\});', script_tag.string).group(1)
            return json.loads(json_text)
        except (AttributeError, json.JSONDecodeError):
            return None
    return None


def remove_json_nulls(obj):
    if isinstance(obj, dict):
        return {k: remove_json_nulls(v) for k, v in obj.items() if v is not None}
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

    return soup.get_text(separator='\n', strip=True)


def data_processing(raw_data, target_url):
    now = datetime.datetime.now(pytz.timezone('Asia/Seoul'))
    current_time_iso = now.isoformat()
    current_date_iso = now.strftime('%Y-%m-%d')
    
    # 1. site_id 조회 및 로깅 강화
    site_id = notice_repo.select_site_id(target_url)
    if site_id is None:
        logger.warning(f"⚠️ 등록되지 않은 URL입니다: {target_url}")


    # 1. DB에서 해당 사이트의 마지막 수집 제목 조회
    last_title = notice_repo.get_latest_notice_title(target_url)

    prompt = raw_processing_prompt.format(
        current_time_iso=current_time_iso,
        current_date_iso=current_date_iso,
        target_url=target_url,  
        raw_data=raw_data,
        last_title=last_title # 프롬프트 변수에 추가
    )

    api_key = os.getenv("GEMINI_API_KEY_DATA_PROCESSING")
    client = genai.Client(api_key=api_key)

    try:
        response = client.models.generate_content(
            model="gemini-flash-lite-latest",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
                response_schema=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "notices": types.Schema(
                            type=types.Type.ARRAY,
                            items=types.Schema(
                                type=types.Type.OBJECT,
                                properties={
                                    "title": types.Schema(type=types.Type.STRING),
                                    "author": types.Schema(type=types.Type.STRING),
                                    "created_at": types.Schema(type=types.Type.STRING),
                                    "scraped_at": types.Schema(type=types.Type.STRING),
                                    "url": types.Schema(type=types.Type.STRING),
                                }
                            )
                        )
                    }
                )
            )
        )

        # ---------------------------------------------------------
        # ✅ [업데이트] Gemini 2.5 Flash Lite 비용 계산 로깅
        # ---------------------------------------------------------
        usage = response.usage_metadata
        in_tokens = usage.prompt_token_count
        out_tokens = usage.candidates_token_count
        
        # 💡 Gemini 2.5 Flash Lite 단가 (예시: 1M 토큰당 $0.075 / $0.30)
        # 환율 1,350원 기준 (입력: 10원/10만 토큰, 출력: 40원/10만 토큰 수준)
        cost_in = (in_tokens / 1_000_000) * 0.075 * 1350
        cost_out = (out_tokens / 1_000_000) * 0.30 * 1350
        total_krw = cost_in + cost_out

        logger.info(
            f"📊 [Gemini 2.5 Flash Lite] {target_url} | "
            f"Tokens: (In:{in_tokens} / Out:{out_tokens}) | "
            f"Cost: ₩{total_krw:.4f}"
        )
        # ---------------------------------------------------------

    except Exception as e:
        logger.error(f"Gemini API 호출 실패: {e}")
        return {"status": "error", "site_id": site_id, "notices": [], "error_msg": str(e)}

    try:
        raw_result = json.loads(response.text)
        if isinstance(raw_result, list):
            result = {"notices": raw_result}
        else:
            result = raw_result

        result['site_id'] = site_id
        result['status'] = "success"

    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"데이터 처리 에러: {e} \n원본 응답: {response.text}")
        return {"status": "error", "site_id": site_id, "notices": []}

    # ✅ 수정된 data_processing 후처리 부분
    # ---------------------------------------------------------
    # 2. 데이터 후처리 및 최종 방어 (완전 수정)
    # ---------------------------------------------------------
    for notice in result.get("notices", []):
        # [A] URL 강제 고정: 추출값 무시하고 무조건 원본 게시판 주소 사용
        notice["url"] = target_url
        
        # [B] created_at 방어: JSON null(None) 대비 및 길이 체크 안전화
        created_at = notice.get("created_at")
        if not created_at or len(str(created_at)) < 10:
            notice["created_at"] = current_time_iso
        
        # [C] scraped_at 누락 보정
        scraped_at = notice.get("scraped_at")
        if not scraped_at:
            notice["scraped_at"] = current_time_iso

    # ---------------------------------------------------------
    # 3. Python 레벨 중복 필터링 (최종 방어)
    # ---------------------------------------------------------
    raw_notices = result.get("notices", [])
    filtered_notices = []

    for notice in raw_notices:
        # LLM이 실수로 가져온 '정보를 가져올 수 없거나...' 문구 필터링
        if "정보를 가져올 수 없거나" in notice.get("title", ""):
            continue
            
        # DB에 있는 최신 제목과 겹치면 그 시점부터 중단
        if notice.get("title") == last_title:
            logger.info(f"🛑 중복 지점 발견 ({last_title}), 이후 데이터 버림.")
            break
            
        filtered_notices.append(notice)

    result["notices"] = filtered_notices

    return result


# -----------------------------------------------------------------------------
# 상세 링크 매핑을 위한 헬퍼 함수 추가
# -----------------------------------------------------------------------------
def normalize_string(text: str) -> str:
    """텍스트 비교의 정확도를 높이기 위해 공백 및 특수문자를 제거하고 소문자로 변환합니다."""
    if not text:
        return ""
    return re.sub(r'\W+', '', text).lower()



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
                logger.info(f"🔗 브릿지 파싱 완료: {clean_url}")
                return clean_url

        return expanded_url
    except requests.RequestException as e:
        logger.error(f"❌ URL 전개 실패: {e}")
        return short_url


def process_notice_request(input_url):
    final_url = expand_url(input_url)
    return get_recent_info(final_url)


def get_recent_info(url):
    logger.info("DB에서 기존 데이터 조회하여 반환합니다.")
    url = expand_url(url)
    
    try:
        # notice_repo.get_all_notices 내부에서도 dict_row를 사용하도록 수정되어야 합니다.
        raw_data = notice_repo.get_all_notices(url)
        site_id = notice_repo.select_site_id(url)

        # 1. 빈 데이터 방어 로직
        if not raw_data:
            logger.warning(f"DB에 저장된 기존 데이터가 없습니다: {url}")
            return {"status": "empty", "site_id": site_id, "notices": []}

        formatted_notices = []
        for row in raw_data:
            # 💡 하드코딩된 인덱스(row[0]) 대신 명확한 컬럼명(row['notice_id'])을 사용합니다.
            formatted_notices.append({
                "notice_id": row['notice_id'],
                "title": row['title'],
                "author": row.get('author') or "", # None일 경우를 대비한 안전장치
                "url": row['url'],
                "created_at": row['created_at'].isoformat() if row.get('created_at') else "",
                "scraped_at": row['scraped_at'].isoformat() if row.get('scraped_at') else "",
            })

        return {"status": "success", "site_id": site_id, "notices": formatted_notices}

    # 2. DB 장애 상황에 대한 안전한 Fallback
    except Exception as e:
        logger.error(f"❌ DB 조회 중 에러 발생 (URL: {url}): {e}")
        # 에러가 발생하더라도 전체 파이프라인이 깨지지 않도록 규격화된 실패 응답 반환
        return {"status": "error", "site_id": None, "notices": []}
    

async def is_crawling_allowed(url, user_agent='*'):
    parsed_url = urlparse(url)
    robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"
    rp = robotparser.RobotFileParser()
    try:
        rp.set_url(robots_url)
        await asyncio.to_thread(rp.read)
    except Exception as e:
        logger.debug(f"robots.txt 확인 불가 (기본 허용): {e}")
        return True

    return rp.can_fetch(user_agent, url)


def sync_notices_to_db(site_id, notices, new_hash, api_url):
    for notice in notices:
        notice_repo.insert_or_update_notice(
            site_id=site_id,
            title=notice.get("title"),
            author=notice.get("author"),
            url=notice.get("url"),
            created_at=notice.get("created_at"),
            scraped_at=notice.get("scraped_at"),
            is_active=True
        )
    notice_repo.deactivate_old_notices(site_id)
    notice_repo.update_api(api_url=api_url, last_hash=new_hash)


def clean_html_text(raw_data):
    clean = re.sub(r'["\']?\w+["\']?\s*[:=]\s*(null|none|nan|undefined),?', '', raw_data, flags=re.IGNORECASE)
    clean = re.sub(r',+', ',', clean)
    return clean.replace(",}", "}").replace(",]", "]").strip()


async def run_full_scrape(url: str) -> dict:
    """
    대상 URL의 데이터를 스크래핑하고 정제하여 DB에 동기화하는 핵심 비동기 함수입니다.
    
    Returns:
        dict: 모든 실행 경로에서 동일한 규격의 딕셔너리를 반환합니다.
              예: {"status": "success"|"error"|"blocked"|"unchanged", "site_id": int, "notices": list}
    """
    global current_data
    url = expand_url(url)
    
    # 💡 [설계 포인트 1] 반환값 규격화 (Interface Standardization)
    # 시스템의 어떤 계층에서 에러가 발생하더라도 워커(Celery)가 예측 가능한 처리를 
    # 할 수 있도록 기본 응답 템플릿을 정의합니다.
    response_template = {"status": "success", "site_id": None, "notices": []}

    def format_response(data: dict, status: str = "success") -> dict:
        """응답 데이터를 템플릿 규격에 맞게 병합하여 반환하는 헬퍼 함수입니다."""
        result = response_template.copy()
        result.update(data)
        result["status"] = status
        return result

    # 1. API 규격 및 메타데이터 조회
    api = await find_api(url)
    if not api:
        logger.error(f"유효한 API 규격을 찾지 못했습니다: {url}")
        return format_response({}, status="error")
    
    site_id = api.get('site_id')
    response_template["site_id"] = site_id

    api_url = api.get('api_url')
    method_type = api.get('method_type')
    headers = api.get('headers', {})
    payload = api.get('payload')

    # 2. 크롤링 윤리 및 차단 방어 (robots.txt 확인)
    # 잠시 해제
    # allowed = await is_crawling_allowed(url, user_agent)
    # if not allowed:
    #     logger.warning(f"⚠ [차단] robots.txt에 의해 크롤링이 금지됨: {url}")
    #     return format_response({}, status="blocked")

    # 3. HTTP 통신 (세션 재사용 및 타임아웃 방어)
    session = requests.Session()
    is_json = 'application/json' in headers.get('content-type', '').lower()
    
    try:
        # 분산 환경에서는 무한 대기(Hang) 방지를 위해 timeout 설정이 필수적입니다.
        if method_type == 'GET':
            response = session.get(api_url, headers=headers, timeout=15)
        else:
            response = session.post(
                api_url, 
                json=payload if is_json else None, 
                data=None if is_json else payload,
                headers=headers,
                timeout=15
            )
        response.encoding = response.apparent_encoding
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ HTTP 요청 실패 (URL: {api_url}): {e}")
        return format_response({}, status="error")

    # DB에 저장된 마지막 상태 해시값 조회
    last_hash = notice_repo.select_last_hash(api_url)
    response_content_type = response.headers.get('Content-Type', '').lower()
    
    # -----------------------------------------------------------
    # 💡 [설계 포인트 2] 전략 패턴(Strategy Pattern) 기반의 파싱 분기 처리
    # 응답 데이터의 형태(JSON vs HTML)에 따라 최적화된 파싱 전략을 선택합니다.
    # -----------------------------------------------------------

    # [전략 A] 순수 JSON 응답 처리
    if 'application/json' in response_content_type:
        logger.info("순수 JSON 응답 감지. 직접 데이터 처리를 진행합니다.")
        try:
            raw_data = response.json()
            cleaned_json = remove_json_nulls(raw_data)
            clean_text = json.dumps(cleaned_json, ensure_ascii=False, separators=(',', ':'))
            new_hash = get_text_hash(clean_text)

            if new_hash != last_hash:
                logger.info("🔄 [변경 감지] 순수 JSON 데이터 동기화 시작")
                clean_data = data_processing(clean_text, url)
                if clean_data and clean_data.get('notices'):
                    sync_notices_to_db(site_id, clean_data.get("notices", []), new_hash, api_url)
                return format_response(clean_data or {}, status="success")
            else:
                recent_info = get_recent_info(url) or {}
                return format_response(recent_info, status="unchanged")
        except json.JSONDecodeError:
            logger.warning("JSON 파싱 실패, HTML 파서(BS4)로 Fallback 진행합니다.")
            # 예외 발생 시 의도적으로 다음 HTML 파싱 블록으로 흐름을 넘깁니다.

    # [전략 B & C] HTML 기반 파싱 (Next.js SSR 데이터 또는 일반 DOM 구조)
    # 크롤러 탐지 우회를 위한 미세한 지연 시간 부여
    await asyncio.sleep(2)
    soup = BeautifulSoup(response.text, 'lxml')
    
    # 텍스트-상세링크 매핑 사전 구축
    next_data = extract_next_data(soup)

    # [전략 B] Next.js 렌더링 데이터(__NEXT_DATA__) 처리
    if next_data:
        cleaned_json = remove_json_nulls(next_data)
        clean_text = json.dumps(cleaned_json, ensure_ascii=False, separators=(',', ':'))
        new_hash = get_text_hash(clean_text)

        if new_hash != last_hash:
            logger.info("🔄 [변경 감지] Next.js 데이터 동기화 시작")
            clean_data = data_processing(clean_text, url)
            
            if clean_data and clean_data.get('notices'):
                sync_notices_to_db(site_id, clean_data.get("notices", []), new_hash, api_url)
            return format_response(clean_data or {}, status="success")
        else:
            recent_info = get_recent_info(url) or {}
            return format_response(recent_info, status="unchanged")

    # [전략 B-1] 유튜브 전용 데이터(ytInitialData) 처리 (LLM 우회 - Pure Python)
    yt_data = extract_yt_data(soup)
    if yt_data:
        logger.info("🎯 유튜브 전용 데이터(ytInitialData) 감지. Python 구조적 파싱을 시작합니다.")
        
        # LLM 호출 없이 바로 파싱
        extracted_notices = parse_youtube_community_data(yt_data, url)
        
        # 해시 비교용 텍스트 생성 (본문들만 모아서 해시화)
        combined_text = "".join([n['title'] for n in extracted_notices])
        new_hash = get_text_hash(combined_text)

        if new_hash != last_hash:
            if extracted_notices:
                sync_notices_to_db(site_id, extracted_notices, new_hash, api_url)
                logger.info(f"✅ 유튜브 데이터 파싱 및 동기화 성공 (Count: {len(extracted_notices)})")
                return format_response({"notices": extracted_notices}, status="success")
            else:
                logger.warning("유튜브 데이터는 찾았으나, 파싱된 게시글이 없습니다.")
        
        recent_info = get_recent_info(url) or {}
        return format_response(recent_info, status="unchanged")


    # [전략 C] 일반 HTML / LLM 기반 파싱 (최후의 보루)
    else:
        # 1. 해시 비교 (불필요한 LLM 호출 방어)
        raw_text = preprocessing(soup)
        clean_text = clean_html_text(raw_text)
        new_hash = get_text_hash(clean_text)

        if new_hash == last_hash:
            logger.info("✅ [변경 없음] 해시 일치. DB 기존 데이터 반환.")
            soup.decompose() # 변경 없으면 즉시 해제
            recent_info = get_recent_info(url) or {}
            return format_response(recent_info, status="unchanged")

        # 2. 내부 헬퍼 함수
        def get_cleaned_extraction(current_soup):
            p_text = preprocessing(current_soup)
            c_text = clean_html_text(p_text)
            return data_processing(c_text, url)

        # 3. [1차 시도] lxml 파서 사용
        logger.info("🤖 [1차 시도] lxml 기반 데이터 정제 시작")
        clean_data = get_cleaned_extraction(soup)

        # 4. [재시도 판단] 데이터가 없거나, 권한 에러 메시지가 온 경우
        should_retry = False
        if not clean_data or not clean_data.get('notices'):
            should_retry = True
        else:
            first_title = clean_data['notices'][0].get('title') or ""
            if "권한이 없거나" in first_title:
                should_retry = True

        logger.info("clean_data → ")

        if should_retry:
            logger.info("♻️ [2차 시도] 파서 변경(html.parser) 및 링크 사전 재구축")
            # 기존 soup 객체 메모리 해제 유도
            del soup
            soup_retry = BeautifulSoup(response.text, 'html.parser')
            
            clean_data = get_cleaned_extraction(soup_retry)
            # 작업 완료 후 명시적 해제
            soup_retry.decompose()

        # 5. [최종 결과 처리] 1차 또는 2차 시도 결과를 가지고 후처리 진행
        if clean_data and clean_data.get('notices'):
            # 상세 링크 매핑 (파이썬 로직)
            
            # DB 동기화
            sync_notices_to_db(site_id, clean_data['notices'], new_hash, api_url)
            logger.info(f"✅ 데이터 추출 및 동기화 성공 (Count: {len(clean_data['notices'])})")
            return format_response(clean_data, status="success")
            
        else:
            # 해시는 변했지만 LLM이 데이터를 하나도 못 찾은 경우
            logger.warning("⚠️ 페이지 변경은 감지되었으나, 유효한 데이터를 추출하지 못했습니다.")
            # 기존 데이터를 보여줄지, 빈 값을 보낼지는 정책에 따라 결정 (여기선 기존 데이터 반환)
            recent_info = get_recent_info(url) or {}
            return format_response(recent_info, status="unchanged")