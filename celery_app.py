import os
import asyncio
import random
from celery import Celery
from celery.schedules import crontab
from celery.utils.log import get_task_logger  # ✅ 필수 임포트 추가
from dotenv import load_dotenv
from kombu import Exchange, Queue

# 기존 임포트 유지
from repositories.notice_repo import get_global_crawl_targets
from dataController.scraper.pipeline.runner import run_full_scrape

# DB 및 알림 서비스 임포트
from repositories.notification_repo import (
    cancel_notification_event,
    claim_notification_event,
    delete_invalid_token,
    finish_notification_event,
    get_pending_event_ids,
    get_ready_deliveries,
    mark_delivery_failed,
    mark_delivery_sent,
)
from services.notify_service import (
    FCMDeliveryError,
    InvalidFCMTokenError,
    send_fcm_notification,
)

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://noticestore_redis:6379/0")
celery_app = Celery("notice_store_worker", broker=REDIS_URL, backend=REDIS_URL)

CRAWL_QUEUE = "crawl"
NOTIFICATION_QUEUE = "notification"
CRAWL_EXCHANGE = Exchange(CRAWL_QUEUE, type="direct")
NOTIFICATION_EXCHANGE = Exchange(NOTIFICATION_QUEUE, type="direct")

# 시간대 설정 (KST 강제 지정)
celery_app.conf.update(
    timezone="Asia/Seoul",
    enable_utc=False,
    task_default_queue=NOTIFICATION_QUEUE,
    task_default_exchange=NOTIFICATION_QUEUE,
    task_default_exchange_type="direct",
    task_default_routing_key=NOTIFICATION_QUEUE,
    task_queues=(
        Queue(
            CRAWL_QUEUE,
            exchange=CRAWL_EXCHANGE,
            routing_key=CRAWL_QUEUE,
        ),
        Queue(
            NOTIFICATION_QUEUE,
            exchange=NOTIFICATION_EXCHANGE,
            routing_key=NOTIFICATION_QUEUE,
        ),
    ),
    task_routes={
        "celery_app.dispatch_all_sites": {
            "queue": CRAWL_QUEUE,
            "routing_key": CRAWL_QUEUE,
        },
        "celery_app.scrape_target_site": {
            "queue": CRAWL_QUEUE,
            "routing_key": CRAWL_QUEUE,
        },
        "celery_app.dispatch_pending_notification_events": {
            "queue": NOTIFICATION_QUEUE,
            "routing_key": NOTIFICATION_QUEUE,
        },
        "celery_app.process_notification_event": {
            "queue": NOTIFICATION_QUEUE,
            "routing_key": NOTIFICATION_QUEUE,
        },
    },
)

# 💡 Celery 전용 로거 인스턴스 생성
logger = get_task_logger(__name__)

# --- [스케줄러 설정] ---
celery_app.conf.beat_schedule = {
    # 1. 기존 크롤링 작업
    'scrape-subscribed-sites-3-times-a-day': {
        'task': 'celery_app.dispatch_all_sites',
        'schedule': crontab(hour='8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18', minute='14'),
        'options': {
            'queue': CRAWL_QUEUE,
            'routing_key': CRAWL_QUEUE,
        },
    },
    # 미발송 outbox 복구용이며 사용자 설정 시각과는 무관합니다.
    'recover-pending-notification-events-every-minute': {
        'task': 'celery_app.dispatch_pending_notification_events',
        'schedule': crontab(minute='*'),
        'options': {
            'queue': NOTIFICATION_QUEUE,
            'routing_key': NOTIFICATION_QUEUE,
        },
    },
}

# --- [구독별 신규 수집 알림 태스크] ---
@celery_app.task(name='celery_app.dispatch_pending_notification_events')
def dispatch_pending_notification_events():
    """Broker 장애 등으로 즉시 처리되지 못한 outbox 이벤트를 복구합니다."""
    event_ids = get_pending_event_ids()
    for event_id in event_ids:
        process_notification_event.delay(event_id)
    return len(event_ids)


@celery_app.task(
    name='celery_app.process_notification_event',
    bind=True,
    max_retries=3,
)
def process_notification_event(self, event_id: int):
    """구독 한 곳의 한 번의 수집 결과를 기기별로 중복 없이 발송합니다."""
    event = claim_notification_event(event_id)
    if not event:
        return {"status": "skipped", "event_id": event_id}

    if not (
        event.get("notification_enabled")
        and event.get("is_notification_enabled")
    ):
        cancel_notification_event(event_id)
        return {"status": "cancelled", "event_id": event_id}

    alias = event.get("alias") or "구독 사이트"
    new_count = int(event.get("new_notice_count") or 0)
    body = f"'{alias}'에 새 소식 {new_count}건이 도착했습니다."
    had_failure = False

    for delivery in get_ready_deliveries(event_id):
        try:
            send_fcm_notification(
                fcm_token=delivery["fcm_token"],
                title="공지저장소 새 소식",
                body=body,
                data={
                    "screen": "subscriptions",
                    "site_id": event["site_id"],
                    "event_id": event_id,
                    "new_notice_count": new_count,
                },
            )
            mark_delivery_sent(delivery["delivery_id"])
        except InvalidFCMTokenError:
            delete_invalid_token(delivery["token_id"])
        except FCMDeliveryError as exc:
            had_failure = True
            delay = 60 * (2 ** int(delivery.get("attempt_count") or 0))
            mark_delivery_failed(delivery["delivery_id"], str(exc), delay)

    retryable = finish_notification_event(event_id)
    if retryable and had_failure:
        raise self.retry(countdown=60)
    return {
        "status": "retrying" if retryable else "complete",
        "event_id": event_id,
    }
    
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
        # 접수 시 확정한 site_id를 끝까지 전달해야 단축 URL/리다이렉트가
        # 전개되어도 앱이 폴링 중인 동일 사이트에 성공/실패가 기록됩니다.
        result = asyncio.run(run_full_scrape(url, site_id=site_id))
        
        # 결과 로깅 (result가 dict 형태라고 가정)
        if isinstance(result, dict):
            for event_id in result.pop('_notification_event_ids', []):
                try:
                    process_notification_event.delay(event_id)
                except Exception as enqueue_error:
                    # 이벤트는 DB에 남아 있으므로 beat 복구 작업이 다시 전달합니다.
                    logger.error(
                        "알림 이벤트 큐 적재 실패 (event_id=%s): %s",
                        event_id,
                        enqueue_error,
                    )
        
        return result

    except Exception as exc:
        logger.error(f"❌ [크롤링 실패] 대상 ID: {site_id}, URL: {url}, 에러: {exc}")
        # 일시적인 네트워크 오류를 대비해 60초 후 최대 3번까지 재시도
        raise self.retry(exc=exc, countdown=60)
