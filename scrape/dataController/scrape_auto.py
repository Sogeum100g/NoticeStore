# 사용자 요청 주소에 대한 method, api_url, header, payload를 넘김
import asyncio
from urllib.parse import urlparse
import requests
import re
from bs4 import BeautifulSoup, Comment
import json

import sys, os

# 다른 경로 파일 불러오기
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))

from dbController import save_db
from dbController import call_db
from dbController import update_db

from dataController.detect_api_auto import find_api
from dotenv import load_dotenv
from google import genai
import datetime
import pytz
from dbController.db_manager import get_db_connection
import hashlib

import yaml
from pathlib import Path

# 1. 파일 로드
CONFIG_PATH = Path(__file__).resolve().parent / "prompt_data.yaml"
with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)


# .env 파일의 환경 변수 로드
load_dotenv()
get_db_connection()
clean_data = ""

# 상위 경로 파일 불러오기
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
file_path = os.path.join(parent_dir, 'tag.json')

with open(file_path) as json_file:
    tag_data = json.load(json_file)

raw_prompt = config['prompts']['json_parser']



# api = asyncio.run(find_api(url))
# print("api 결정 : ", api)
# 2. api 저장
# method_type = api.get('method_type')
# api_url = api.get('api_url')
# headers = api.get('headers')
# payload  = api.get('payload') if api.get('payload') else None

# 디버깅용
# print("url : ", url)
# print("method_type : ", method_type)
# print("api_url : ", api_url)
# print("headers : ", headers)
# print("payload : ", payload)
# print("header 타입 : ", type(headers))
# print("payload 타입 : ", type(payload))


# Next.js의 표준 데이터 태그를 찾습니다.
def extract_next_data(soup):
    script_tag = soup.find('script', id='__NEXT_DATA__')

    if script_tag:
        # 태그 내부의 JSON 문자열을 딕셔너리로 변환
        data = json.loads(script_tag.string)
        # 이 데이터가 바로 이전에 우리가 LLM으로 변환했던 그 정형 데이터입니다.
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

# session = requests.Session()

# 5. 요청
# if method_type == 'GET':
#     print("session.get ----> ")
#     response = session.get(api_url, headers=headers)
#
# else:
#     print("session.post ----> ")
#     response = session.post(api_url, params=payload, headers=headers)
#
# response.encoding = response.apparent_encoding # 서버가 제공한 실제 인코딩으로 강제 설정


def preprocessing(soup):
    """
    HTML DOM에서 무의미한 태그 및 주석을 제거하고
    정제된 텍스트만 반환한다.
    """

    # 2. 해당 태그들 한 번에 찾아 삭제
    for element in soup.find_all(tag_data["trash_tags"]):
        element.decompose()

    # 3. HTML 주석() 및 CDATA 섹션 제거
    # string=lambda... 문법을 사용하여 모든 Comment 객체를 찾아 삭제합니다.
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # 4. 결과 반환 (텍스트만 필요할 경우 soup.get_text(), HTML이 필요할 경우 str(soup))
    # 여기서는 텍스트 추출을 기준으로 작성합니다.
    clean_text = soup.get_text(separator='\n', strip=True)
    return clean_text


def data_processing(raw_data, target_url):
    now = datetime.datetime.now(pytz.timezone('Asia/Seoul'))
    current_time_iso = now.isoformat()
    prompt1 = f"""
**역할**: 당신은 웹 페이지의 복잡한 텍스트에서 '사용자가 정보를 받기 위해 실제로 읽어야 할 핵심 리스트'를 추출하는 데이터 엔지니어입니다.

**데이터 보존 원칙 (CRITICAL)**:
1. **절대 생략 금지**: 페이지 메인 영역에 나열된 모든 개별 항목(이벤트, 강연, 공지 등)은 하나도 빠짐없이 추출하세요.
2. **리스트 최우선**: 사이트 좌/우측, 또는 상단/하단의 메뉴(회사소개, 약관, 광고 등)보다 페이지 중앙의 '컨텐츠 리스트'가 최우선 순위입니다.
3. **데이터 무결성**: 텍스트가 조금 지저분하더라도 정보(제목, 날짜)가 포함되어 있다면 반드시 포함하세요.

**미션**: 제공된 [데이터 리스트]에서 공지사항 정보를 추출하여 DB 스키마에 맞게 JSON으로 변환하세요.

**입력 스키마 및 가이드**:
1. **title**: 게시글 제목에서 'N', '새글', 'zip'과 같은 시스템 아이콘용 텍스트는 제거하되, 제목에 포함된 '★'이나 '▶' 같은 강조용 특수문자와 문장 부호는 그대로 유지하세요.
2. **author**: 작성 기관 또는 작성자 명
3. **url**: 입력으로 들어온 target_url을 그대로 사용하세요.
4. **content_preview**: 본문 미리보기. 리스트에 내용이 없다면 빈 문자열("")로 처리
5. **created_at**: 게시글 등록일 (ISO 8601 형식: YYYY-MM-DDTHH:mm:ss+09:00)
6. **scraped_at**: 현재 데이터 처리 시각. 반드시 "{current_time_iso}"를 사용하세요.

**데이터 특징**:
- '첨부파일', '파일다운로드' 등의 아이콘 텍스트는 무시하세요.
- 중복된 게시글은 `title`과 `created_at`을 기준으로 하나만 남깁니다.
- 하나의 공고 내에 '모집분야'가 여러 개 나열되어 있을 경우, 각 직무(예: 서비스 개발/운영, AI 엔지니어 등)를 개별 게시글로 간주하여 각각 추출하세요.
- 각 직무별 '업무 내용 및 자격 요건'을 `content_preview`에 요약하여 포함하세요.
- 여러개의 'title' 발견 시 한 줄로 나열하지 말고 분리하세요.

[중요: 예외 처리] 
   - 데이터 리스트가 비어 있거나(empty), 분석 가능한 게시글이 없을 경우: title을 "권한이 없거나 정보를 가져올 수 없습니다."로 지정하여 한 개의 데이터를 생성하세요. 

   
[데이터 리스트] : {raw_data}

**응답 형식**: 반드시 아래 JSON 포맷을 엄격히 준수하세요.
{{
  "notices": [
    {{
      "title": "문자열",
      "author": "문자열",
      "url": "문자열",
      "content_preview": "문자열",
      "created_at": "datetime",
      "scraped_at": "datetime"
    }}
  ]
}}
"""



    prompt2 = f"""
**역할**: 당신은 커뮤니티 게시판의 복잡한 비정형 텍스트에서 '유효한 게시글 목록'만 골라내어 구조화된 JSON으로 변환하는 데이터 엔지니어입니다.

**미션**: [데이터 리스트]에서 네비게이션 메뉴, 광고, 차단 설정 등의 노이즈를 제외하고, 실제 사용자가 작성한 게시글 리스트만 추출하세요.

**입력 스키마 및 가이드**:
1. **title**: 게시글 제목.
   - 제목 끝의 [댓글수], 'N', '새글', 'zip', '이미지/동영상 아이콘' 표시 등은 모두 제거하고 순수 제목만 남기세요.
2. **author**: 작성자 닉네임 또는 ID. (IP 주소 일부가 포함된 경우 그대로 유지)
3. **url**: 입력으로 들어온 target_url을 그대로 사용하세요.
4. **content_preview**: 게시글 미리보기.
   - 목록에 내용이 노출되지 않는 '리스트형' 게시판인 경우 빈 문자열("")로 처리하세요.
5. **created_at**: 게시글 등록 시각 (ISO 8601 형식 준수: YYYY-MM-DDTHH:mm:ss+09:00)
   - **날짜 변환 규칙**:
     - '10:24'와 같이 시간만 있다면 오늘 날짜인 "{current_time_iso[:10]}"을 결합하세요.
     - '01-22'와 같이 월/일만 있다면 연도는 "{current_time_iso[:4]}"를 사용하세요.
     - '방금 전', 'n분 전' 등 상대 시간은 "{current_time_iso}"를 기준으로 계산하여 고정 시각으로 변환하세요.
6. **scraped_at**: 데이터를 처리한 현재 시각. 반드시 "{current_time_iso}"를 사용하세요.
7. **reason**: 이 데이터를 선택한 이유를 간단하게 설명하세요

**데이터 특징 및 주의사항**:
1. 커뮤니티 특성상 제목에 '설문', 'AD', '공지'가 붙은 것은 가급적 포함하되, 사이트 하단의 회사소개/약관 등의 메뉴와는 엄격히 구분하세요.
2. 번호 | 말머리 | 제목 | 글쓴이 | 작성일 | 조회 | 추천 순서로 반복되는 패턴을 찾으세요.
3. 중복된 게시글은 `title`과 `created_at`을 기준으로 하나만 남깁니다.
4. [중요: 예외 처리] 
   - 데이터 리스트가 비어 있거나(empty), 분석 가능한 게시글이 없을 경우: title을 "권한이 필요합니다"로 지정하여 한 개의 데이터를 생성하세요. 
   - reason 필드에 왜 데이터가 없는지 사유를 기록하세요.
   
[데이터 리스트] : {raw_data}

**응답 형식**: 반드시 아래 JSON 포맷을 엄격히 준수하세요. (JSON 이외의 설명은 생략하세요)
{{
  "notices": [
    {{
      "title": "문자열",
      "author": "문자열",
      "url": "문자열",
      "content_preview": "문자열",
      "created_at": "datetime",
      "scraped_at": "datetime"
      "reason": ""
    }}
  ]
}}



"""

    # 3. Gemini 연결
    api_key = os.getenv("GEMINI_API_KEY_DATA_PROCESSING")
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        # 프롬프트 입력
        contents=prompt1,
        config={'response_mime_type': 'application/json'}
    )

    result = json.loads(response.text)


    # 2. 결과 내의 모든 url을 urljoin으로 보정
    for notice in result.get("notices", []):
        original_url = notice.get("url")
        if original_url:
            # request_url(사용자가 넣은 URL)을 기준으로 절대 경로 변환
            notice["url"] = target_url
    print(type(result))
    return result

def get_text_hash(text: str) -> str:
    # 텍스트를 바이트로 변환 후 SHA-256 해싱
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def get_recent_info(url):
    print("DB에서 기존 데이터 조회하여 반환")
    raw_data = call_db.get_all_notices(url)

    # 앱이 기대하는 필드명(title, author, content_preview 등)으로 규격을 맞춥니다.
    formatted_notices = []
    for row in raw_data:
        formatted_notices.append({
            "notice_id": row[0],
            "title": row[1],
            "author": row[2] or "",
            "url": row[3],
            "content_preview": row[4] or "",
            # DateTime 객체는 반드시 문자열(isoformat)로 변환해야 앱에서 파싱 가능합니다.
            "created_at": row[5].isoformat() if row[5] else "",
            "scraped_at": row[6].isoformat() if row[6] else "",
        })

    print("data : ", formatted_notices)
    return {"status": "success", "data": formatted_notices}

# if response.status_code == 200:
#     # 응답이 JSON이 아닌 HTML 조각이므로 BS4로 파싱
#     soup = BeautifulSoup(response.text, 'lxml')
#     next_data = extract_next_data(soup)
#
#     if next_data:
#         cleaned_data = remove_json_nulls(next_data)
#         clean_text = json.dumps(cleaned_data, ensure_ascii=False)
#
#         new_hash = get_text_hash(clean_text)
#         last_hash = call_db.select_last_hash(url)
#
#         # 긁어보니 값이 달라졌으면
#         if new_hash != last_hash:
#             clean_data = data_processing(clean_text, url)
#             # DB에 데이터 저장
#             # save_notice 로직
#
#             site_id = call_db.select_site_id(url)
#
#             # clean_data['notices'] 리스트를 순회하며 하나씩 저장합니다.
#             for notice in clean_data.get("notices", []):
#                 save_db.insert_notice(
#                     site_id=site_id,
#                     title=notice.get("title"),
#                     author=notice.get("author"),
#                     url=notice.get("url"),
#                     content_preview=notice.get("content_preview"),
#                     created_at=notice.get("created_at"),
#                     scraped_at=notice.get("scraped_at")
#                 )
#             update_db.update_api(
#                 api_url=api.get('api_url'),
#                 last_hash=new_hash
#             )
#
#     else :
#         data = soup.get_text(separator='\n', strip=True)
#         # text = clean_text_noise(data)
#
#         # "key": null 형태와 그 뒤의 쉼표까지 한 번에 찾아 지우는 패턴
#         clean_text = re.sub(r'["\']?\w+["\']?\s*[:=]\s*(null|none|nan|undefined),?', '', data, flags=re.IGNORECASE)
#         # 연속된 쉼표를 하나로 합치거나 제거
#         clean_text = re.sub(r',+', ',', clean_text)
#         # 마지막에 남은 쉼표 제거
#         clean_text = clean_text.replace(",}", "}").replace(",]", "]")
#
#         new_hash = get_text_hash(clean_text)
#         last_hash = call_db.select_last_hash(api.get('api_url'))
#
#         print("new_hash : ", new_hash)
#         print("last_hash", last_hash)
#         # 긁어보니 값이 달라졌으면
#         if new_hash != last_hash:
#             print("변경 감지 -> LLM 호출 및 데이터 정제 시작")
#             clean_data = data_processing(clean_text, url)
#
#
#             print(clean_text)
#             print(clean_data)
#             print("===================================================")
#             print("new_hash : ", new_hash)
#             print("last_hash : ", last_hash)
#
#             # DB에 데이터 저장
#             # save_notice 로직
#
#             site_id = call_db.select_site_id(url)
#
#             # clean_data['notices'] 리스트를 순회하며 하나씩 저장합니다.
#             # DB의 last_hash를 new_hash로 업데이트
#             for notice in clean_data.get("notices", []):
#                 save_db.insert_notice(
#                     site_id=site_id,
#                     title=notice.get("title"),
#                     author=notice.get("author"),
#                     url=notice.get("url"),
#                     content_preview=notice.get("content_preview"),
#                     created_at=notice.get("created_at"),
#                     scraped_at=notice.get("scraped_at")
#                 )
#             update_db.update_api(
#                 api_url=api.get('api_url'),
#                 last_hash=new_hash
#             )
# else:
#     print("response status code : ", response.status_code)

# ===========================================================================================================
# ===========================================================================================================
# ===========================================================================================================

async def run_full_scrape(url: str):

    api = await find_api(url)
    print("api 결정 : ", api)

    # 2. api 저장
    method_type = api.get('method_type')
    api_url = api.get('api_url')
    headers = api.get('headers')
    payload = api.get('payload') if api.get('payload') else None

    # 디버깅용
    print("url : ", url)
    print("method_type : ", method_type)
    print("api_url : ", api_url)
    print("headers : ", headers)
    print("payload : ", payload)
    print("header 타입 : ", type(headers))
    print("payload 타입 : ", type(payload))



    session = requests.Session()
    session.get(url, headers=headers)

    # 5. 요청
    # 현재 헤더 설정 확인
    is_json = headers.get('content-type') == 'application/json'

    if method_type == 'GET':
        response = session.get(api_url, headers=headers)
    else:  # POST일 경우
        if is_json:
            # 로그에 찍힌 방식: JSON 본문에 담아 보내야 함
            response = session.post(api_url, json=payload, headers=headers)
        else:
            # 일반 폼 데이터 방식
            response = session.post(api_url, data=payload, headers=headers)

    response.encoding = response.apparent_encoding  # 서버가 제공한 실제 인코딩으로 강제 설정

    if response.status_code == 200:
        # 응답이 JSON이 아닌 HTML 조각이므로 BS4로 파싱
        soup = BeautifulSoup(response.text, 'lxml')
        next_data = extract_next_data(soup)

        if next_data:
            cleaned_data = remove_json_nulls(next_data)
            clean_text = json.dumps(cleaned_data, ensure_ascii=False)

            new_hash = get_text_hash(clean_text)
            last_hash = call_db.select_last_hash(url)

            # 긁어보니 값이 달라졌으면
            if new_hash != last_hash:
                clean_data = data_processing(clean_text, url)
                # DB에 데이터 저장
                # save_notice 로직

                site_id = call_db.select_site_id(url)

                # clean_data['notices'] 리스트를 순회하며 하나씩 저장합니다.
                for notice in clean_data.get("notices", []):
                    save_db.insert_notice(
                        site_id=site_id,
                        title=notice.get("title"),
                        author=notice.get("author"),
                        url=notice.get("url"),
                        content_preview=notice.get("content_preview"),
                        created_at=notice.get("created_at"),
                        scraped_at=notice.get("scraped_at")
                    )
                update_db.update_api(
                    api_url=api.get('api_url'),
                    last_hash=new_hash
                )

        else:
            data = soup.get_text(separator='\n', strip=True)
            # text = clean_text_noise(data)

            # "key": null 형태와 그 뒤의 쉼표까지 한 번에 찾아 지우는 패턴
            clean_text = re.sub(r'["\']?\w+["\']?\s*[:=]\s*(null|none|nan|undefined),?', '', data, flags=re.IGNORECASE)
            # 연속된 쉼표를 하나로 합치거나 제거
            clean_text = re.sub(r',+', ',', clean_text)
            # 마지막에 남은 쉼표 제거
            clean_text = clean_text.replace(",}", "}").replace(",]", "]")

            new_hash = get_text_hash(clean_text)
            last_hash = call_db.select_last_hash(api.get('api_url'))

            print("new_hash : ", new_hash)
            print("last_hash : ", last_hash)
            # 긁어보니 값이 달라졌으면
            if new_hash != last_hash:
                print("변경 감지 -> LLM 호출 및 데이터 정제 시작")
                clean_data = data_processing(clean_text, url)

                print(clean_text)
                print(clean_data)
                print("===================================================")
                print("new_hash : ", new_hash)
                print("last_hash : ", last_hash)

                # DB에 데이터 저장
                # save_notice 로직

                site_id = call_db.select_site_id(url)

                # clean_data['notices'] 리스트를 순회하며 하나씩 저장합니다.
                # DB의 last_hash를 new_hash로 업데이트
                for notice in clean_data.get("notices", []):
                    save_db.insert_notice(
                        site_id=site_id,
                        title=notice.get("title"),
                        author=notice.get("author"),
                        url=notice.get("url"),
                        content_preview=notice.get("content_preview"),
                        created_at=notice.get("created_at"),
                        scraped_at=notice.get("scraped_at")
                    )
                update_db.update_api(
                    api_url=api.get('api_url'),
                    last_hash=new_hash
                )

                # if 'clean_data' in locals() and clean_data:
                #     # clean_data['notices']에 실제 리스트가 들어있으므로 이것만 꺼냅니다.
                #     raw_data = call_db.get_all_notices(url)
                #     return {"status": "success", "data": raw_data}
                # else:
                #     return {"status": "success", "data": []}

                return get_recent_info(url)

            else: # 해시값이 같을 때
                return get_recent_info(url)


    else:
        print("response status code : ", response.status_code)
        return {"status": "success", "data": []}

# 1. 요청 주소
url = "https://careers.kakao.com/jobs?skillSet=&page=1&company=KAKAO&part=TECHNOLOGY&employeeType=&keyword="
# asyncio.run(run_full_scrape(url))