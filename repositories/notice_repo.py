import datetime
import psycopg
from typing import Optional, List, Dict, Any
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

# 공통 DB 커넥션 매니저 임포트
from repositories.db_manager import get_db_connection

# --- [1. 사이트(Site) 및 크롤링 API 관리] ---

def insert_site(site_url: str, created_at: datetime.datetime) -> Optional[int]:
    """새로운 사이트를 등록하고 생성된 site_id를 반환합니다."""
    conn = get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            query = """
                INSERT INTO sites (site_url, created_at)
                VALUES (%s, %s)
                RETURNING site_id;
            """
            cur.execute(query, (site_url, created_at))
            result = cur.fetchone()
            if result:
                new_site_id = result[0]
                conn.commit()
                print(f"새 사이트 저장 완료 (ID: {new_site_id})")
                return new_site_id
            else:
                print(f"사이트 중복 : {site_url}")
                return None
    except Exception as e:
        print(f"에러 발생: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

def insert_api(site_id: int, method_type: str, api_url: str, headers: dict, payload: dict, last_hash: str) -> Optional[int]:
    """사이트의 크롤링 API 설정 정보를 저장합니다."""
    conn = get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            query = """
                INSERT INTO api (site_id, method_type, api_url, headers, payload, created_at, scraped_at, last_hash)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW(), %s)
                RETURNING api_id;
            """
            cur.execute(query, (site_id, method_type, api_url, Jsonb(headers), Jsonb(payload), last_hash))
            result = cur.fetchone()
            if result:
                new_api_id = result[0]
                conn.commit()
                print(f"새 API 설정 저장 완료 (ID: {new_api_id})")
                return new_api_id
            else:
                print(f"api_url 중복 : {api_url}")
                return None
    except Exception as e:
        print(f"에러 발생: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

def update_api(api_url: str, last_hash: str):
    """크롤링 후 API의 해시값과 마지막 실행 시간을 갱신합니다."""
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cur:
            query = """
                UPDATE api
                SET last_hash = %s,
                    scraped_at = NOW()
                WHERE api_url = %s;
            """
            cur.execute(query, (last_hash, api_url))
            conn.commit()
    except Exception as e:
        print(f"❌ API 업데이트 에러: {e}")
        conn.rollback()
    finally:
        conn.close()

def select_api(target_url: str) -> Optional[Dict[str, Any]]:
    """크롤링 타겟 사이트의 API 설정 정보(헤더, 페이로드 등)를 가져옵니다."""
    conn = get_db_connection()
    if not conn: return None
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            # SELECT 절에 s.site_id 를 명시적으로 추가했습니다.
            query = """
                SELECT s.site_id, a.method_type, a.api_url, a.headers, a.payload, a.created_at
                FROM sites s
                JOIN api a ON s.site_id = a.site_id
                WHERE s.site_url = %s;
            """
            cur.execute(query, (target_url,))
            result = cur.fetchone()
            if result:
                print(f"[{target_url}] 설정을 성공적으로 불러왔습니다.")
                return result
            else:
                print(f"[{target_url}]에 해당하는 API 설정이 없습니다.")
                return None
    except Exception as e:
        print(f"데이터 불러오기 중 에러 발생: {e}")
        return None
    finally:
        conn.close()

def select_site_id(url: str) -> Optional[int]:
    """주어진 URL을 기반으로 sites 테이블에서 site_id를 조회합니다."""
    conn = get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            query = "SELECT site_id FROM sites WHERE site_url = %s;"
            cur.execute(query, (url, ))
            result = cur.fetchone()
            if result:
                return result[0]
            else:
                print(f"[{url}]에 해당하는 site 정보가 없습니다.")
                return None
    finally:
        conn.close()

def select_last_hash(url: str) -> Optional[str]:
    """특정 API URL의 마지막 크롤링 해시값을 조회하여 데이터 변경 여부를 파악합니다."""
    conn = get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            query = "SELECT last_hash FROM api WHERE api_url = %s;"
            cur.execute(query, (url, ))
            result = cur.fetchone()
            if result:
                return result[0]
            else:
                print(f"{url}에 해당하는 hash값이 없습니다.")
                return None
    finally:
        conn.close()

def get_sites_with_new_status() -> List[tuple]:
    """시스템에 등록된 모든 사이트 정보와 새 공지 존재 여부를 반환합니다."""
    conn = get_db_connection()
    if not conn: return []
    try:
        with conn.cursor() as cur:
            query = """
            SELECT s.site_id, s.site_url, s.last_viewed_at,
                EXISTS (
                    SELECT 1 FROM notices n 
                    WHERE n.site_id = s.site_id 
                    AND n.created_at > s.last_viewed_at
                    AND n.created_at > COALESCE(s.last_viewed_at, '1970-01-01 00:00:00')
                ) as has_new
            FROM sites s;
            """
            cur.execute(query)
            rows = cur.fetchall()
            return rows if rows else []
    finally:
        conn.close()

def update_view_time(site_id: int):
    """특정 사이트 자체의 마지막 조회 시간을 갱신합니다."""
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cur:
            query = "UPDATE sites SET last_viewed_at = NOW() WHERE site_id = %s;"
            cur.execute(query, (site_id,))
            conn.commit()
            print(f"Site {site_id} 전체 읽음 처리 완료")
    except Exception as e:
        conn.rollback()
        print(f"업데이트 중 오류 발생: {e}")
    finally:
        conn.close()

# --- [2. 구독(Subscription) 관리] ---

def get_user_specific_sites(user_id: int) -> List[tuple]:
    """특정 사용자의 구독 목록과 새 소식 여부를 판단하여 가져옵니다."""
    conn = get_db_connection()
    if not conn: return []
    try:
        with conn.cursor() as cur:
            # 마지막 동기화 시간 이후에 새롭게 등록된(created_at) 공지가 하나라도 있는지 확인
            query = """
                    SELECT s.site_id, s.site_url, us.alias,
                    CASE 
                        WHEN us.last_synced_at IS NULL THEN true
                        WHEN EXISTS (
                            SELECT 1 FROM notices n 
                            WHERE n.site_id = s.site_id 
                            AND n.created_at > us.last_synced_at
                        ) THEN true
                        ELSE false 
                    END as has_new
                    FROM user_subscriptions us
                    JOIN sites s ON us.site_id = s.site_id
                    WHERE us.user_id = %s;
                """
            cur.execute(query, (user_id,))
            return cur.fetchall()
    except Exception as e:
        print(f"사용자별 사이트 조회 중 오류: {e}")
        return []
    finally:
        conn.close()

def add_user_subscription(user_id: int, site_id: int, alias: str):
    """사용자의 구독 목록에 사이트를 추가합니다. 중복 시 별명(alias)만 갱신합니다."""
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cur:
            query = """
                INSERT INTO user_subscriptions (user_id, site_id, alias, last_synced_at)
                VALUES (%s, %s, %s, '2000-01-01 00:00:00')
                ON CONFLICT (user_id, site_id) 
                DO UPDATE SET alias = EXCLUDED.alias;
            """
            cur.execute(query, (user_id, site_id, alias))
            conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"구독 추가 중 오류 발생: {e}")
    finally:
        conn.close()

def delete_user_subscription(user_id: int, site_id: int) -> bool:
    """사용자의 특정 사이트 구독을 취소(삭제)합니다."""
    conn = get_db_connection()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            query = "DELETE FROM user_subscriptions WHERE user_id = %s AND site_id = %s;"
            cur.execute(query, (user_id, site_id))
            if cur.rowcount > 0:
                conn.commit()
                print(f"User {user_id}의 Site {site_id} 구독 취소 완료.")
                return True
            else:
                return False
    except Exception as e:
        conn.rollback()
        print(f"❌ 구독 취소 중 데이터베이스 오류 발생: {e}")
        return False
    finally:
        conn.close()

def update_user_view_time(site_id: int, user_id: int):
    """사용자가 구독 중인 사이트를 확인했을 때 동기화 시간(last_synced_at)을 갱신합니다."""
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cur:
            query = """
                UPDATE user_subscriptions 
                SET last_synced_at = NOW() 
                WHERE site_id = %s AND user_id = %s;
            """
            cur.execute(query, (site_id, user_id))
            conn.commit()
            print(f"User {user_id} - Site {site_id} 개인화 읽음 처리 완료")
    except Exception as e:
        conn.rollback()
        print(f"업데이트 중 오류 발생: {e}")
    finally:
        conn.close()

# --- [3. 공지사항(Notice) 관리] ---

def insert_notice(site_id: int, title: str, author: str, url: str, created_at: datetime.datetime, scraped_at: datetime.datetime) -> Optional[int]:
    """공지사항을 데이터베이스에 새로 저장합니다. 중복 시 무시(DO NOTHING)합니다."""
    conn = get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            query = """
                INSERT INTO notices (site_id, title, author, url, created_at, scraped_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (site_id, title, author) DO NOTHING
                RETURNING notice_id;
            """
            cur.execute(query, (site_id, title, author, url, created_at, scraped_at))
            result = cur.fetchone()
            if result:
                new_notice_id = result[0]
                conn.commit()
                print(f"새 공지사항 저장 완료 (ID: {new_notice_id}), {title[:30]}")
                return new_notice_id
            else:
                print(f"중복된 공지사항 건너뜀: {title[:20]}...")
                return None
    except Exception as e:
        print(f"에러 발생: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

def insert_or_update_notice(site_id: int, title: str, author: str, url: str, created_at: datetime.datetime, scraped_at: datetime.datetime, is_active: bool = True):
    """
    공지사항을 저장하거나, 이미 존재할 경우 정보를 업데이트하고 활성화 상태로 변경합니다.
    (site_id, title) 제약 조건에 맞춰 작동하며, 제목의 공백을 정규화하여 중복을 방지합니다.
    """
    conn = get_db_connection()
    if not conn:
        return

    # 💡 [핵심] 제목 정규화: LLM이 만든 미세한 공백 차이를 DB 제약 조건과 일치시킵니다.
    # 연속된 공백을 한 칸으로 줄이고 앞뒤 공백을 제거합니다.
    clean_title = " ".join(title.split()).strip() if title else ""
    clean_author = author.strip() if author else ""
    clean_url = url.strip() if url else ""

    # 💡 [안전장치] LLM이 날짜를 못 찾았을 경우, 수집 시점을 생성일로 간주합니다.
    # 이렇게 하면 DB의 NOT NULL 제약조건을 지키면서 '최초 발견일' 원칙을 유지합니다.
    final_created_at = created_at if created_at else scraped_at

    try:
        with conn.cursor() as cur:
            # ON CONFLICT 대상에서 author를 제외하고 (site_id, title)만 사용합니다.
            query = """
                INSERT INTO notices (
                    site_id, title, author, url, created_at, scraped_at, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (site_id, title) 
                DO UPDATE SET 
                    url = EXCLUDED.url,           -- 상세 URL이 확보되면 갱신되도록 포함
                    scraped_at = EXCLUDED.scraped_at,
                    is_active = EXCLUDED.is_active;
            """
            cur.execute(query, (site_id, clean_title, clean_author, clean_url, final_created_at, scraped_at, is_active))
            conn.commit()
            
    except Exception as e:
        print(f"❌ 데이터 저장/업데이트 중 에러 발생: {e}")
        conn.rollback()
    finally:
        conn.close()

def deactivate_old_notices(site_id: int):
    """DB 최적화를 위해 3개월이 경과한 공지사항을 비활성화 처리합니다."""
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cur:
            query = """
                UPDATE notices
                SET is_active = false
                WHERE site_id = %s
                  AND is_active = true
                  AND created_at < CURRENT_TIMESTAMP - INTERVAL '3 months';
            """
            cur.execute(query, (site_id,))
            conn.commit()
            print(f"✅ [Sync] Site ID {site_id}의 오래된 공지 {cur.rowcount}개가 비활성화되었습니다.")
    except Exception as e:
        print(f"❌ 비활성화 에러: {e}")
        conn.rollback()
    finally:
        conn.close()

def get_all_notices(url: str) -> List[tuple]:
    """단일 사이트의 활성화된 모든 공지사항을 가져옵니다."""
    conn = get_db_connection()
    if not conn: return []
    try:
        with conn.cursor() as cur:
            query = """
                SELECT n.notice_id, n.title, n.author, n.url, n.created_at, n.scraped_at
                FROM notices n
                JOIN sites s ON n.site_id = s.site_id
                WHERE s.site_url = %s AND n.is_active = true
                ORDER BY n.created_at DESC;
            """
            cur.execute(query, (url, ))
            result = cur.fetchall()
            return result if result else []
    finally:
        conn.close()

def get_latest_notice_title(url: str) -> str:
    """해당 URL에서 가장 최근에 저장된 공지사항의 제목을 반환합니다."""
    notices = get_all_notices(url)
    if notices:
        # result[0]은 (notice_id, title, author, url, created_at, scraped_at) 형태입니다.
        return notices[0][1] # title 필드 반환
    return "없음"


def get_all_user_notices(user_id: int) -> List[dict]:
    """
    사용자가 구독한 모든 사이트의 공지 목록을 최신순으로 가져옵니다.
    사용자가 숨김 처리한(user_hidden_notices) 공지는 제외합니다.
    결과는 dict_row를 사용하여 딕셔너리 리스트로 반환합니다.
    """
    conn = get_db_connection()
    if not conn: 
        return []
        
    try:
        # 💡 psycopg3의 row_factory=dict_row를 사용하여 결과를 딕셔너리로 받습니다.
        with conn.cursor(row_factory=dict_row) as cur:
            query = """
                SELECT n.notice_id, n.title, n.author, n.url, n.created_at, n.scraped_at, n.site_id
                FROM notices n
                INNER JOIN user_subscriptions us ON n.site_id = us.site_id
                WHERE us.user_id = %s
                AND n.is_active = true
                AND NOT EXISTS (
                    SELECT 1 
                    FROM user_hidden_notices uhn 
                    WHERE uhn.notice_id = n.notice_id 
                    AND uhn.user_id = %s
                )
                ORDER BY n.created_at DESC;
            """
            cur.execute(query, (user_id, user_id))
            result = cur.fetchall()
            
            # 이제 result는 [{"notice_id": 1, "title": "..."}, ...] 형태입니다.
            return result if result else []
            
    except Exception as e:
        print(f"❌ 공지 목록 조회 중 에러 발생: {e}")
        return []
    finally:
        conn.close()

def hide_user_notice(user_id: int, notice_id: int) -> bool:
    """사용자가 개별 공지를 피드에서 숨김 처리합니다."""
    conn = get_db_connection()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            query = """
                INSERT INTO user_hidden_notices (user_id, notice_id, created_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (user_id, notice_id) DO NOTHING;
            """
            cur.execute(query, (user_id, notice_id))
            conn.commit()
            print(f"User {user_id}의 Notice {notice_id} 숨김 처리 완료.")
            return True
    except Exception as e:
        conn.rollback()
        print(f"❌ 개별 공지 숨김 중 오류 발생: {e}")
        return False
    finally:
        conn.close()


def get_global_crawl_targets() -> List[dict]:
    """
    [시스템 전용] 구독자가 1명이라도 있는 모든 사이트를 중복 없이 조회합니다.
    """
    conn = get_db_connection()
    if not conn: return []
    try:
        # 💡 psycopg3 컨벤션에 맞춰 row_factory=dict_row 적용
        with conn.cursor(row_factory=dict_row) as cur:
            # Celery 태스크가 target.get('url')을 사용하므로 site_url을 url로 별칭 지정
            query = """
                SELECT DISTINCT s.site_id, s.site_url AS url
                FROM sites s
                JOIN user_subscriptions us ON s.site_id = us.site_id;
            """
            cur.execute(query)
            return cur.fetchall()
        
    except Exception as e:
        print(f"❌ 전역 크롤링 대상 조회 실패: {e}") 
        return []
    finally:
        conn.close()