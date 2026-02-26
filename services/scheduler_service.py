from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

from repositories.user_repo import get_users_to_notify, get_notice_summary_for_user
# 💡 앞서 작성하신 파일 경로에 맞게 임포트 경로를 수정해 주세요.

from services.notify_service import send_fcm_notification

# 백그라운드 스케줄러 인스턴스 생성
scheduler = BackgroundScheduler()

def job_check_and_send_notifications():
    """
    1분마다 실행되며, 조건에 맞는 사용자에게 푸시 알림을 발송합니다.
    """
    # 1. 현재 시간 포맷팅 (예: '18:00')
    now_str = datetime.now().strftime("%H:%M")
    print(f"⏰ [스케줄러] {now_str} - 알림 대상자 확인 중...")

    # 2. DB에서 현재 시간이 알림 시간과 일치하는 사용자 조회
    users = get_users_to_notify(now_str)
    print(f"👤 [스케줄러] 조회된 발송 대상자 수: {len(users)}명")

    if not users:
        return

    # 3. 대상자들에게 각각 알림 발송 처리
    for user in users:
        user_id = user['user_id']
        fcm_token = user['fcm_token']

        # 해당 사용자의 신규 공지 요약 문구 생성
        summary_msg = get_notice_summary_for_user(user_id)

        # 신규 공지가 있을 때만 발송
        if summary_msg:
            send_fcm_notification(
                fcm_token=fcm_token,
                title="공지저장소 업데이트",
                body=summary_msg,
                # 💡 [핵심 추가] 알림 클릭 시 앱 내 'subscriptions' 화면으로 이동하도록 데이터 포함
                data={"screen": "subscriptions"}
            )

def start_scheduler():
    """스케줄러를 시작하고 작업을 등록합니다."""
    # job_check_and_send_notifications 함수를 1분 주기로 실행되도록 등록
    scheduler.add_job(job_check_and_send_notifications, 'interval', minutes=1)
    scheduler.start()
    print("✅ 백그라운드 알림 스케줄러가 가동되었습니다.")

def stop_scheduler():
    """스케줄러를 안전하게 종료합니다."""
    scheduler.shutdown()
    print("🛑 백그라운드 알림 스케줄러가 종료되었습니다.")