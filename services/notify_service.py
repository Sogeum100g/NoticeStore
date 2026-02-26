from typing import Optional

import firebase_admin
from firebase_admin import credentials, messaging
import os

# 💡 다운로드한 서비스 계정 키 경로
JSON_PATH = "clients/notice-store-firebase-adminsdk-fbsvc-dc41f1152a.json"

if not firebase_admin._apps:
    cred = credentials.Certificate(JSON_PATH)
    firebase_admin.initialize_app(cred)


def initialize_firebase():
    """
    Firebase Admin SDK를 초기화합니다.
    서버 구동 시 또는 최초 발송 시 한 번만 실행되도록 보장합니다.
    """
    if not firebase_admin._apps:
        # 💡 이전 단계에서 준비한 서비스 계정 키 파일의 경로
        cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "firebase-secret.json")

        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            print("✅ Firebase Admin SDK가 성공적으로 초기화되었습니다.")
        else:
            print("⚠️ Firebase 크리덴셜 파일을 찾을 수 없습니다. 경로를 확인해주세요.")


def send_fcm_notification(fcm_token: str, title: str, body: str, data: Optional[dict] = None) -> bool:
    """
    단일 기기의 FCM 토큰으로 푸시 메시지를 전송합니다.
    """
    initialize_firebase()

    if not fcm_token:
        print("⚠️ 전송 실패: FCM 토큰이 누락되었습니다.")
        return False

    # FCM의 data 페이로드는 모든 값을 반드시 '문자열(String)'로 변환해서 보내야 합니다.
    # 이를 처리하지 않으면 Firebase 내부에서 타입 에러가 발생하여 서버가 다운될 수 있습니다.
    safe_data = {str(k): str(v) for k, v in data.items()} if data else {}

    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=safe_data,
            token=fcm_token,
        )

        response = messaging.send(message)
        print(f"✅ FCM 푸시 발송 성공 (Message ID: {response})")
        return True

    except Exception as e:
        print(f"❌ FCM 푸시 발송 실패: {e}")
        return False