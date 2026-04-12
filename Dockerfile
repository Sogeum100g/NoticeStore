# 1. Playwright 공식 이미지 사용
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# 2. 작업 디렉토리 설정
WORKDIR /app

# 💡 [핵심 수정] 타임존 설치 시 대화창 차단 및 순서 조정
# ENV를 사용해 빌드 과정 전체에서 대화창이 뜨지 않게 설정합니다.
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata && \
    ln -sf /usr/share/zoneinfo/Asia/Seoul /etc/localtime && \
    echo "Asia/Seoul" > /etc/timezone && \
    rm -rf /var/lib/apt/lists/*

# 3. 라이브러리 목록 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 4. Playwright 브라우저 및 의존성 설치
RUN playwright install chromium --with-deps

# 5. 소스 코드 복사
COPY . .

# 6. 실행 명령 (CMD는 항상 가장 마지막에!)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]