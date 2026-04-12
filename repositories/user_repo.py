from typing import Optional, Dict, Any, List, Union, Tuple
from psycopg.rows import dict_row
from datetime import datetime

# 공통 DB 커넥션 매니저 임포트
from repositories.db_manager import get_db_connection


def get_or_create_user(
    email: str, 
    social_id: str, 
    provider: str, 
    fcm_token: str = None, 
    device_id: str = None, 
    device_type: str = None,
    referrer_code: str = None
) -> Optional[Dict[str, Any]]:
    """
    사용자를 조회 또는 생성하고, 동시에 접속한 기기의 정보를 최신 상태로 유지합니다.
    """
    conn = get_db_connection()
    if not conn: return None

    try:
        with conn.cursor() as cur:
            # 1. 기존 유저 확인 및 생성 로직
            cur.execute("SELECT user_id FROM users WHERE social_id = %s", (social_id,))
            user = cur.fetchone()

            target_user_id = None

            if user:
                target_user_id = user[0]
                print(f"📡 기존 유저 로그인: {email} (ID: {target_user_id})")
            else:
                # 신규 유저: users 테이블 삽입 (fcm_token 컬럼 제외)
                default_nickname = email.split('@')[0] if email else "User"
                cur.execute(
                    """
                    INSERT INTO users (social_id, provider, email, nickname, max_sites_limit, max_keywords_limit, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) 
                    RETURNING user_id
                    """,
                    (social_id, provider, email, default_nickname, 5, 1000, datetime.now())
                )
                target_user_id = cur.fetchone()[0]
                print(f"✨ 신규 유저 가입: {email} (ID: {target_user_id})")

                # 추천인 보상 로직 (신규 가입 시에만 수행)
                if referrer_code:
                    try:
                        referrer_id = int(referrer_code)
                        cur.execute("SELECT user_id FROM users WHERE user_id = %s", (referrer_id,))
                        if cur.fetchone():
                            cur.execute("INSERT INTO referrals (referrer_id, referee_id) VALUES (%s, %s)", (referrer_id, target_user_id))
                            cur.execute("UPDATE users SET max_sites_limit = max_sites_limit + 1 WHERE user_id = %s", (referrer_id,))
                            print(f"🎁 추천인({referrer_id}) 보상 지급 완료")
                    except Exception as ref_e:
                        print(f"⚠️ 추천인 처리 중 에러: {ref_e}")

            # 2. 계정 관련 변경 사항 확정 (Commit)
            conn.commit()

        # 3. 기기 토큰 정보 업데이트 (Upsert)
        # 계정 생성/조회에 성공한 경우에만 기기 정보를 등록합니다.
        if target_user_id and fcm_token and device_id:
            upsert_success = upsert_device_fcm_token(
                user_id=target_user_id,
                fcm_token=fcm_token,
                device_id=device_id,
                device_type=device_type
            )
            if not upsert_success:
                print(f"⚠️ [FCM] 기기 토큰 업데이트 실패 (User: {target_user_id}, Device: {device_id})")

        # 4. 최신 유저 정보 반환
        from repositories.user_repo import get_user_info_by_id 
        return get_user_info_by_id(target_user_id)

    except Exception as e:
        if conn: conn.rollback()
        print(f"❌ [DB 에러] get_or_create_user 실패: {e}")
        return None
    finally:
        if conn: conn.close()



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
                SELECT user_id, email, nickname, provider, social_id, 
                       is_notification_enabled, notification_time, role,
                       max_sites_limit, max_keywords_limit
                FROM users 
                WHERE user_id = %s
            """
            cur.execute(query, (user_id,))
            row = cur.fetchone()

            if row:
                # 💡 핵심 개선: 커서의 description에서 컬럼명들을 추출하여 동적으로 딕셔너리 생성
                column_names = [desc[0] for desc in cur.description]
                return dict(zip(column_names, row))
            else:
                return None
    except Exception as e:
        print(f"❌ [DB 에러] get_user_info_by_id 실행 중 오류 발생: {e}")
        return None
    finally:
        conn.close()

def update_user_notification_settings(user_id: int, is_enabled: bool = None, time_str: str = None) -> bool:
    """
    사용자의 전역 알림 설정(시간, 활성화 여부)을 업데이트합니다.
    기기별 FCM 토큰은 upsert_device_fcm_token 함수가 별도로 관리합니다.
    """
    conn = get_db_connection()
    if not conn: return False

    try:
        with conn.cursor() as cur:
            # 💡 fcm_token 컬럼 수정을 쿼리에서 제거했습니다.
            query = """
                UPDATE users 
                SET 
                    is_notification_enabled = COALESCE(%s, is_notification_enabled), 
                    notification_time = COALESCE(%s, notification_time)
                WHERE user_id = %s
            """
            cur.execute(query, (is_enabled, time_str, user_id))
            conn.commit()
            
            # 업데이트가 발생했다면 rowcount는 1 이상입니다.
            success = cur.rowcount > 0
            if success:
                print(f"✅ DB 알림 설정 업데이트 완료 (User: {user_id}, Enabled: {is_enabled}, Time: {time_str})")
            return success
            
    except Exception as e:
        print(f"❌ [DB 에러] update_user_notification_settings 실패: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def upsert_device_fcm_token(user_id: int, fcm_token: str, device_id: str, device_type: str) -> bool:
    """사용자의 기기별 FCM 토큰을 추가하거나 최신 상태로 갱신(Upsert)합니다."""
    conn = get_db_connection()
    if not conn: return False

    try:
        with conn.cursor() as cur:
            # ON CONFLICT 구문을 사용하여 user_id와 device_id가 중복될 경우 업데이트를 수행합니다.
            query = """
                INSERT INTO user_fcm_tokens (user_id, fcm_token, device_id, device_type, last_updated_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, device_id) 
                DO UPDATE SET 
                    fcm_token = EXCLUDED.fcm_token,
                    last_updated_at = CURRENT_TIMESTAMP;
            """
            cur.execute(query, (user_id, fcm_token, device_id, device_type))
            conn.commit()
            
            # INSERT 또는 UPDATE가 발생하면 rowcount는 1 이상입니다.
            return cur.rowcount > 0
    except Exception as e:
        print(f"❌ [DB 에러] upsert_device_fcm_token 실패: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_user_fcm_tokens(user_id: int) -> list:
    """
    특정 사용자의 모든 기기에 등록된 FCM 토큰 목록을 반환합니다.
    결과는 리스트 형태이며, 토큰이 없거나 에러 발생 시 빈 리스트 []를 반환합니다.
    """
    conn = get_db_connection()
    if not conn: 
        return []

    try:
        # 💡 dict_row를 사용하면 결과에 키값으로 접근하기 쉬워집니다.
        with conn.cursor() as cur:
            # 1. 쿼리 교정: used_id 오타 수정 및 user_id 기준 조회
            query = """
                SELECT fcm_token
                FROM user_fcm_tokens
                WHERE user_id = %s
            """
            cur.execute(query, (user_id,))
            
            # 2. fetchall()을 사용하여 모든 기기의 토큰을 리스트 형태로 가져옵니다. [cite: 2026-03-10]
            rows = cur.fetchall()
            
            # 딕셔너리의 키 이름으로 안전하게 접근
            return [row['fcm_token'] for row in rows] if rows else []

    except Exception as e:
        print(f"❌ [DB 에러] get_user_fcm_tokens 조회 실패: {e}")
        return []
    finally:
        conn.close()



def delete_device_fcm_token(user_id: int, device_id: str) -> bool:
    """로그아웃 시 특정 기기의 FCM 토큰 정보를 삭제합니다."""
    conn = get_db_connection()
    if not conn: return False

    try:
        with conn.cursor() as cur:
            query = "DELETE FROM user_fcm_tokens WHERE user_id = %s AND device_id = %s"
            cur.execute(query, (user_id, device_id))
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        print(f"❌ [DB 에러] delete_device_fcm_token 실패: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_users_to_notify(now_str: str) -> List[Dict[str, Any]]:
    """설정된 알림 시간이 일치하고 수신이 켜져 있는 유저들의 모든 토큰 목록을 반환합니다."""
    conn = get_db_connection()
    if not conn: return []

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            # 💡 [핵심] JOIN을 통해 유저 설정과 기기 토큰을 결합합니다.
            query = """
                SELECT u.user_id, t.fcm_token 
                FROM users u
                INNER JOIN user_fcm_tokens t ON u.user_id = t.user_id
                WHERE u.is_notification_enabled = true 
                  AND u.notification_time = %s;
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
                  AND n.created_at > COALESCE(us.last_synced_at, '1970-01-01'::timestamp)
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

def get_user_max_sites_limit(user_id: int) -> int:
    """사용자별로 허용된 최대 사이트 개수(상한선)를 가져옵니다."""
    conn = get_db_connection()
    if not conn: return 5 # DB 연결 실패 시 기본 한도(예: 5개) 부여

    try:
        with conn.cursor() as cur:
            # WHERE 절의 컬럼명은 실제 테이블의 PK 컬럼명(예: id 또는 user_id)으로 맞추세요.
            query = """
                SELECT max_sites_limit 
                FROM users 
                WHERE user_id = %s; 
            """
            cur.execute(query, (user_id,))  # 💡 튜플 형태로 전달
            result = cur.fetchone()
            
            if result and result[0] is not None:
                return int(result[0])  # 💡 튜플에서 숫자만 추출
            return 5 # 데이터가 없을 경우의 기본값
            
    except Exception as e:
        print(f"최대 한도 조회 에러 발생: {e}")
        return 5
    finally:
        conn.close()


def get_current_subscription_count(user_id: int) -> int:
    """사용자가 현재 구독 중인 사이트의 총 개수를 가져옵니다."""
    conn = get_db_connection()
    if not conn: return 0

    try:
        with conn.cursor() as cur:
            # 구독 테이블에서 해당 유저의 레코드 개수를 셉니다. (테이블명 확인 필요)
            query = """
                SELECT COUNT(*) 
                FROM user_subscriptions 
                WHERE user_id = %s;
            """
            cur.execute(query, (user_id,))
            result = cur.fetchone()
            
            if result:
                return int(result[0])
            return 0
            
    except Exception as e:
        print(f"구독 개수 조회 에러 발생: {e}")
        return 0
    finally:
        conn.close()


def delete_user_account(user_id: int) -> bool:
    """
    사용자의 계정을 데이터베이스에서 삭제합니다.
    (PostgreSQL의 ON DELETE CASCADE 기능에 의해 구독, 폴더, 키워드, 문의 내역 등 
    모든 연관 데이터가 자동으로 안전하게 연쇄 삭제됩니다.)
    """
    conn = get_db_connection()
    if not conn: return False

    try:
        with conn.cursor() as cur:
            # 💡 단일 쿼리로 부모 테이블만 삭제하면 DB가 나머지를 알아서 처리합니다.
            query = "DELETE FROM users WHERE user_id = %s"
            cur.execute(query, (user_id,))
            
            conn.commit()
            
            # rowcount가 0보다 크면 실제 데이터가 삭제되었음을 의미합니다.
            if cur.rowcount > 0:
                print(f"✅ DB 사용자 회원탈퇴 및 연관 데이터 연쇄 삭제 완료 (User ID: {user_id})")
                return True
            else:
                print(f"⚠️ 삭제할 사용자를 찾을 수 없습니다. (User ID: {user_id})")
                return False
                
    except Exception as e:
        conn.rollback()
        print(f"❌ [DB 에러] delete_user_account 실행 중 오류 발생: {e}")
        return False
    finally:
        conn.close()