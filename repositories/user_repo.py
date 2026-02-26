from typing import Optional, Dict, Any, List
from psycopg.rows import dict_row
from datetime import datetime

# 공통 DB 커넥션 매니저 임포트
from repositories.db_manager import get_db_connection


def get_or_create_user(email: str, social_id: str, provider: str, fcm_token: str = None) -> Optional[int]:
    """
    사용자를 조회하고, 없으면 새로 생성하며,
    로그인 시마다 FCM 토큰을 최신화합니다.
    """
    conn = get_db_connection()
    if not conn: return None

    cur = conn.cursor()

    try:
        # 1. 기존 유저 확인 (social_id 기준)
        cur.execute("SELECT user_id FROM users WHERE social_id = %s", (social_id,))
        user = cur.fetchone()

        if user:
            # 2. 기존 유저라면 FCM 토큰만 최신화 (기기 변경 대응)
            user_id = user[0]
            cur.execute(
                "UPDATE users SET fcm_token = %s WHERE user_id = %s",
                (fcm_token, user_id)
            )
            print(f"📡 기존 유저 로그인: {email} (FCM 토큰 갱신)")
        else:
            # 3. 신규 유저라면 데이터 삽입 (ERD 설계 준수)
            cur.execute(
                """
                INSERT INTO users (social_id, provider, email, fcm_token, max_sites_limit, max_keywords_limit, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING user_id
                """,
                (social_id, provider, email, fcm_token, 10, 5, datetime.now())
            )
            user_id = cur.fetchone()[0]
            print(f"✨ 신규 유저 가입: {email}")

        conn.commit()
        return user_id

    except Exception as e:
        conn.rollback()
        print(f"❌ DB 에러: {e}")
        return None
    finally:
        cur.close()
        conn.close()


def update_user_nickname(user_id: int, new_nickname: str) -> bool:
    """사용자의 닉네임을 업데이트합니다."""
    conn = get_db_connection()
    if not conn: return False

    try:
        with conn.cursor() as cur:
            query = "UPDATE users SET nickname = %s WHERE user_id = %s"
            cur.execute(query, (new_nickname, user_id))
            conn.commit()
            return True
    except Exception as e:
        conn.rollback()
        print(f"❌ DB 닉네임 업데이트 중 에러 발생: {e}")
        return False
    finally:
        conn.close()


def get_user_info_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """user_id(PK)를 사용하여 최신 유저 정보를 딕셔너리로 반환합니다."""
    conn = get_db_connection()
    if not conn: return None

    try:
        with conn.cursor() as cur:
            query = """
                SELECT user_id, email, nickname, provider, social_id, fcm_token,
                       is_notification_enabled, notification_time, role
                FROM users 
                WHERE user_id = %s
            """
            cur.execute(query, (user_id,))
            row = cur.fetchone()

            if row:
                return {
                    "user_id": row[0],
                    "email": row[1],
                    "nickname": row[2],
                    "provider": row[3],
                    "social_id": row[4],
                    "fcm_token": row[5],
                    "is_notification_enabled": row[6],
                    "notification_time": row[7],
                    "role": row[8]
                }
            return None
    except Exception as e:
        print(f"❌ [DB 에러] get_user_info_by_id 실행 중 오류 발생: {e}")
        return None
    finally:
        conn.close()


def update_user_notification_settings(user_id: int, is_enabled: bool = None, time_str: str = None,
                                      fcm_token: str = None) -> bool:
    """사용자의 알림 설정(FCM 토큰, 시간, 활성화 여부)을 업데이트합니다."""
    conn = get_db_connection()
    if not conn: return False

    try:
        with conn.cursor() as cur:
            query = """
                UPDATE users 
                SET 
                    is_notification_enabled = COALESCE(%s, is_notification_enabled), 
                    notification_time = COALESCE(%s, notification_time),
                    fcm_token = COALESCE(%s, fcm_token) 
                WHERE user_id = %s
            """
            cur.execute(query, (is_enabled, time_str, fcm_token, user_id))
            conn.commit()
            print(f"✅ DB 알림 설정 업데이트 완료 (User: {user_id})")
            return cur.rowcount > 0
    except Exception as e:
        print(f"❌ DB 에러: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def update_user_fcm_token(user_id: int, fcm_token: str) -> bool:
    """사용자의 기기 FCM 토큰을 갱신합니다."""
    conn = get_db_connection()
    if not conn: return False

    try:
        with conn.cursor() as cur:
            query = "UPDATE users SET fcm_token = %s WHERE user_id = %s"
            cur.execute(query, (fcm_token, user_id))
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        print(f"❌ [DB 에러] update_user_fcm_token 실패: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_users_to_notify(now_str: str) -> List[Dict[str, Any]]:
    """설정된 알림 시간이 일치하고 수신이 켜져 있는 유저 목록을 반환합니다."""
    conn = get_db_connection()
    if not conn: return []

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            query = """
                SELECT DISTINCT ON (fcm_token) user_id, fcm_token 
                FROM users 
                WHERE is_notification_enabled = true 
                  AND notification_time = %s 
                  AND fcm_token IS NOT NULL;
            """
            cur.execute(query, (now_str,))
            return cur.fetchall()
    except Exception as e:
        print(f"❌ 알림 대상자 조회 중 에러 발생: {e}")
        return []
    finally:
        conn.close()


def get_notice_summary_for_user(user_id: int) -> Optional[str]:
    """사용자별로 새로 업데이트된 공지사항의 요약 문구를 생성합니다."""
    conn = get_db_connection()
    if not conn: return None

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            query = """
                SELECT DISTINCT us.alias
                FROM user_subscriptions us
                JOIN notices n ON us.site_id = n.site_id
                WHERE us.user_id = %s
                  AND n.scraped_at > COALESCE(us.last_synced_at, '1970-01-01'::timestamp)
            """
            cur.execute(query, (user_id,))
            results = cur.fetchall()

            if not results: return None

            aliases = [row['alias'] for row in results if row['alias']]
            if not aliases: return None

            if len(aliases) == 1:
                return f"'{aliases[0]}'에 새로운 공지가 추가되었습니다."
            else:
                return f"'{aliases[0]}' 외 {len(aliases) - 1}곳에 새 소식이 도착했습니다."

    except Exception as e:
        print(f"❌ 알림 요약 문구 생성 중 에러 발생 (User {user_id}): {e}")
        return None
    finally:
        conn.close()