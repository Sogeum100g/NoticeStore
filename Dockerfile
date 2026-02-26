# 1. Playwright 브라우저 구동 환경이 완벽히 세팅된 공식 이미지를 사용합니다. (파이썬도 포함됨)
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# 2. 컨테이너 내부의 작업 디렉토리 설정
WORKDIR /app

# 3. 필요한 라이브러리 목록 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. 크롤링에 필요한 크로미움 브라우저와 OS 의존성 패키지를 컨테이너 내부에 설치
RUN playwright install chromium --with-deps

# 5. 전체 코드 복사 (라우터, 리포지토리 등 모두 포함)
COPY . .

# 6. FastAPI 서버 실행 (8000번 포트)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]