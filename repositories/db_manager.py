import psycopg
import os
from dotenv import load_dotenv

# .env 파일의 환경 변수 로드
load_dotenv()

def get_db_connection():
    try:
        connection = psycopg.connect(
            host=os.getenv("DB_HOST"),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            port=os.getenv("DB_PORT")
        )
        return connection
    except Exception as e:
        print(f"DB 연결 실패: {e}")
        return None