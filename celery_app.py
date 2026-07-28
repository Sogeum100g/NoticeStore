import os
import asyncio
from datetime import datetime
import random
from zoneinfo import ZoneInfo
from celery import Celery
from celery.schedules import crontab
from celery.utils.log import get_task_logger  # ✅ 필수 임포트 추가
from dotenv import load_dotenv

# 기존 임포트 유지
from repositories.notice_repo import get_global_crawl_targets
from dataController.scraper.scrape_auto import run_full_scrape

# DB 및 알림 서비스 임포트
from repositories.user_repo import get_users_to_notify, get_notice_summary_for_user
from services.notify_service import send_fcm_notification

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://noticestore_redis:6379/0")
celery_app = Celery("notice_store_worker", broker=REDIS_URL, backend=REDIS_URL)

# 시간대 설정 (KST 강제 지정)
celery_app.conf.timezone = 'Asia/Seoul'
celery_app.conf.enable_utc = False

# 💡 Celery 전용 로거 인스턴스 생성
logger = get_task_logger(__name__)

# --- [스케줄러 설정] ---
celery_app.conf.beat_schedule = {
    # 1. 기존 크롤링 작업
    'scrape-subscribed-sites-3-times-a-day': {
        'task': 'celery_app.dispatch_all_sites',
        'schedule': crontab(hour='9, 13, 17', minute='14'),
    },
    # 2. 신규: 1분마다 알림 발송 대상자 확인 (단일 등록)
    'check-and-send-notifications-every-minute': {
        'task': 'celery_app.check_notifications',
        'schedule': crontab(minute='*'), # 매 분마다 실행
    },
}

# --- [신규 알림 태스크] ---
@celery_app.task(name='celery_app.check_notifications')
def check_notifications():
    """매 분마다 실행되어 조건에 맞는 사용자에게 알림을 발송합니다."""
    kst = ZoneInfo('Asia/Seoul')
    now_str = datetime.now(kst).strftime("%H:%M") 
    logger.info(f"⏰ {now_str} (KST) - 알림 대상자 확인 중...") # 💡 print -> logger.info

    # 주의: FastAPI에서 DB 접근 함수가 비동기(async def)로 작성되어 있다면 
    # 아래와 같이 asyncio.run()으로 감싸서 호출해야 합니다.
    # 동기 함수(def)라면 users = get_users_to_notify(now_str) 로 그대로 둡니다.
    try:
        # 예시: 만약 get_users_to_notify가 비동기 함수라면
        # users = asyncio.run(get_users_to_notify(now_str))
        
        # 동기 함수라면:
        users = get_users_to_notify(now_str)
    except Exception as e:
        logger.error(f"❌ 대상자 조회 실패: {e}", exc_info=True) # 💡 스택 트레이스 포함
        return
    
    if not users:
        return

    logger.info(f"👤 [Celery 스케줄러] 조회된 발송 대상자 수: {len(users)}명. 개별 큐 발송 시작...")

    for user in users:
        user_id = user['user_id']
        fcm_token = user['fcm_token']
        
        # 마찬가지로 비동기 함수 여부에 따라 호출 방식을 맞춰주세요.
        summary_msg = get_notice_summary_for_user(user_id)
        
        if summary_msg:
            # 개별 알림 전송을 별도의 워커에게 비동기로 위임 (Fan-out)
            send_fcm_task.delay(fcm_token, summary_msg)

@celery_app.task(name='celery_app.send_fcm_task', bind=True, max_retries=3)
def send_fcm_task(self, fcm_token: str, summary_msg: str):
    """실제 FCM 서버로 통신을 담당하는 워커 태스크"""
    try:
        # 동기/비동기 여부 확인 후 적용 필요
        send_fcm_notification(
            fcm_token=fcm_token,
            title="센트리피전 업데이트",
            body=summary_msg,
            data={"screen": "subscriptions"}
        )
        logger.info(f"✅ FCM 전송 성공: {fcm_token[:10]}...")
    except Exception as exc:
        logger.error(f"❌ FCM 전송 실패, 재시도 중... 에러: {exc}")
        # 실패 시 10초 후 재시도
        raise self.retry(exc=exc, countdown=10)
    
# --- [크롤링 작업 분배 및 실행 태스크 리팩토링] ---

@celery_app.task(name='celery_app.dispatch_all_sites')
def dispatch_all_sites():
    """
    정해진 시간에 실행되어 구독 중인 모든 사이트 목록을 DB에서 가져오고,
    각 사이트별로 지터(Jitter)를 적용하여 크롤링 큐에 적재합니다.
    """
    # 1. DB에서 크롤링 대상 목록 조회 (List[dict] 반환)
    targets = get_global_crawl_targets()
    
    if not targets:
        return

    # 2. 각 타겟 사이트별로 비동기 태스크 예약
    for target in targets:
        site_id = target.get('site_id')
        url = target.get('url')
        
        if not site_id or not url:
            continue
            
        # 0초 ~ 300초(5분) 사이의 랜덤한 지연 시간 생성 (Jitter 적용)
        jitter_delay = random.randint(0, 300)
        
        # 워커에게 작업을 지시하되, countdown 속성으로 지연 실행을 예약
        scrape_target_site.apply_async(args=[site_id, url], countdown=jitter_delay)


@celery_app.task(name='celery_app.scrape_target_site', bind=True, max_retries=3)
def scrape_target_site(self, site_id: int, url: str):
    """
    Redis 큐에서 작업을 꺼내어 실제 크롤링을 수행하는 워커 태스크입니다.
    """
    try:
        
        # 비동기(async) 함수를 동기(Celery) 환경에서 실행하기 위해 이벤트 루프 할당
        result = asyncio.run(run_full_scrape(url))
        
        # 결과 로깅 (result가 dict 형태라고 가정)
        status = result.get('status', 'success') if isinstance(result, dict) else 'success'
        
        return result

    except Exception as exc:
        logger.error(f"❌ [크롤링 실패] 대상 ID: {site_id}, URL: {url}, 에러: {exc}")
        # 일시적인 네트워크 오류를 대비해 60초 후 최대 3번까지 재시도
        raise self.retry(exc=exc, countdown=60)