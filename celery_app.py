import os
import asyncio
import random
from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

from repositories.notice_repo import get_global_crawl_targets
from scrape.dataController.scrape_auto import run_full_scrape

load_dotenv()

# 1. Celery 애플리케이션 초기화 (Redis 브로커 연결)
REDIS_URL = os.getenv("REDIS_URL", "redis://noticestore_redis:6379/0")

celery_app = Celery(
    "notice_store_worker",
    broker=REDIS_URL,
    backend=REDIS_URL
)

# 2. 한국 시간대 설정 (매우 중요: 서버 시간이 UTC일 경우 10시가 한국의 19시로 오작동할 수 있음)
celery_app.conf.timezone = 'Asia/Seoul'

# 3. 비트 스케줄 설정 (크롤링 주기 고정)
celery_app.conf.beat_schedule = {
    'scrape-subscribed-sites-3-times-a-day': {
        'task': 'celery_app.dispatch_all_sites',
        'schedule': crontab(hour='10,14,20', minute='0'),  # 10시, 14시, 20시 정각
    },
}


# 4. 작업 분배기 태스크 (Jitter 적용)
@celery_app.task(name='celery_app.dispatch_all_sites')
def dispatch_all_sites():
    """
    정해진 시간에 실행되어 구독 중인 모든 사이트 목록을 가져오고,
    각 사이트별로 지터를 적용하여 크롤링 큐에 적재합니다.
    """
    sites = get_global_crawl_targets()
    print(f"총 {len(sites)}개의 구독 사이트 크롤링 태스크를 큐에 분배합니다.")

    for site in sites:
        url = site['url']
        # 0초 ~ 300초(5분) 사이의 랜덤한 지연 시간 생성 (Jitter)
        jitter_delay = random.randint(0, 300)

        # 워커에게 작업을 지시하되, countdown 속성으로 지연 실행을 예약
        scrape_target_site.apply_async(args=[url], countdown=jitter_delay)
        print(f"➔ [Dispatch 예약 완료] {url} (지연: {jitter_delay}초)")


# 5. 실제 크롤링 워커 태스크 (Async 래핑 및 재시도 로직)
@celery_app.task(name='celery_app.scrape_target_site', bind=True, max_retries=3)
def scrape_target_site(self, url: str):
    """
    Redis 큐에서 작업을 꺼내어 실제 크롤링을 수행합니다.
    """
    try:
        print(f"▶️ [크롤링 시작] 대상 URL: {url}")

        # 💡 핵심: 비동기(async) 함수를 동기(Celery) 환경에서 실행하기 위해 이벤트 루프 할당
        result = asyncio.run(run_full_scrape(url))

        print(f"✅ [크롤링 완료] 대상 URL: {url}, 결과: {result.get('status', 'success')}")
        return result

    except Exception as exc:
        print(f"❌ [크롤링 실패] 대상 URL: {url}, 에러: {exc}")
        # 일시적인 네트워크 오류를 대비해 60초 후 최대 3번까지 재시도
        raise self.retry(exc=exc, countdown=60)