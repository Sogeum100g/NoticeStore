from typing import Optional

import firebase_admin
from firebase_admin import credentials, messaging
import os

# 모듈 최상단에 있던 하드코딩된 초기화 코드는 삭제했습니다.

def initialize_firebase():
    """
    Firebase Admin SDK를 초기화합니다.
    서버 구동 시 또는 최초 발송 시 한 번만 실행되도록 보장합니다.
    """
    if not firebase_admin._apps:
        # .env 파일에 FIREBASE_CREDENTIALS_PATH=/app/firebase-secret.json 형태로 지정하는 것을 권장합니다.
        cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "notice-store-firebase-adminsdk-fbsvc-dc41f1152a.json")

        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            print("✅ Firebase Admin SDK가 성공적으로 초기화되었습니다.")
        else:
            print(f"⚠️ Firebase 크리덴셜 파일을 찾을 수 없습니다. 경로: {cred_path}")


def send_fcm_notification(fcm_token: str, title: str, body: str, data: Optional[dict] = None) -> bool:
    """단일 기기의 FCM 토큰으로 푸시 메시지를 전송합니다."""
    initialize_firebase()

    if not fcm_token:
        print("⚠️ 전송 실패: FCM 토큰이 누락되었습니다.")
        return False

    safe_data = {str(k): str(v) for k, v in data.items()} if data else {}

    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    channel_id="high_importance_channel", 
                    sound="default"
                )
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default", badge=1)
                )
            ),
            data=safe_data,
            token=fcm_token,
        )

        response = messaging.send(message)
        print(f"✅ FCM 푸시 발송 성공 (Message ID: {response})")
        return True

    except messaging.UnregisteredError:
        print(f"🗑️ 만료된 토큰 발견. 앱을 삭제한 유저일 가능성이 높습니다: {fcm_token}")
        # DB에서 해당 토큰을 무효화하거나 삭제하는 로직을 이곳에 연결해야 합니다.
        # 예: user_repo.delete_fcm_token(fcm_token)
        return False
        
    except Exception as e:
        print(f"❌ FCM 푸시 발송 실패: {e}")
        return False