from datetime import datetime

# 💡 프로젝트에 구성된 celery_app 객체의 실제 임포트 경로로 수정해주세요.
from celery_app import celery_app 

from repositories.user_repo import get_users_to_notify, get_notice_summary_for_user
from services.notify_service import send_fcm_notification

@celery_app.task
def task_check_and_send_notifications():
    """
    1분마다 실행되며, 여러 기기를 가진 사용자에게도 누락 없이 알림을 발송합니다.
    """
    now_str = datetime.now().strftime("%H:%M")
    print(f"⏰ [Celery 스케줄러] {now_str} - 알림 대상자 확인 중...")

    raw_results = get_users_to_notify(now_str)
    
    if not raw_results:
        return

    # 1. 사용자별로 토큰을 그룹화합니다. (메시지 생성 중복 방지)
    user_tokens_map = {}
    for row in raw_results:
        uid = row['user_id']
        token = row['fcm_token']
        if uid not in user_tokens_map:
            user_tokens_map[uid] = []
        user_tokens_map[uid].append(token)

    print(f"👤 [Celery 스케줄러] 발송 대상 사용자: {len(user_tokens_map)}명")

    # 2. 사용자별로 메시지를 생성하여 해당 사용자의 모든 기기에 발송합니다.
    for user_id, tokens in user_tokens_map.items():
        # 요약 메시지는 사용자당 딱 한 번만 생성합니다. [cite: 2025-10-01]
        summary_msg = get_notice_summary_for_user(user_id)

        if summary_msg:
            for fcm_token in tokens:
                send_fcm_notification(
                    fcm_token=fcm_token,
                    title="센트리피전 새 소식",
                    body=summary_msg,
                    data={"screen": "subscriptions"}
                )