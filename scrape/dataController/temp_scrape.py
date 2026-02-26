# 사용자 요청 주소에 대한 method, api_url, header, payload를 넘김
from urllib.parse import urlparse
import requests
import re
from bs4 import BeautifulSoup
import json

import sys, os

# 다른 경로 파일 불러오기
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))

from dbController import save_db
from dbController import call_db
from dbController import update_db

from detect_api_auto import find_api
from dotenv import load_dotenv
from repositories.db_manager import get_db_connection

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

# 1. 요청 주소
url = "https://hanwhasystems-ict-recruit.co.kr/"
base_url = urlparse(url).netloc



async def run_full_scrape(url: str):

    api = await find_api(url)

    # 2. api 저장
    method_type = api.get('method_type')
    api_url = api.get('api_url')
    headers = api.get('headers')
    payload  = api.get('payload') if api.get('payload') else None

    session = requests.Session()

    # 5. 요청
    if method_type == 'GET':
        print("session.get ----> ")
        response = session.get(api_url, headers=headers)

    else:
        print("session.post ----> ")
        response = session.post(api_url, params=payload, headers=headers)

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
            print("last_hash", last_hash)
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

    else:
        print("response status code : ", response.status_code)















