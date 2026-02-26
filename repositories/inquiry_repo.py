from typing import Optional, List, Dict, Any
from psycopg.rows import dict_row

# 공통 DB 커넥션 매니저 임포트
from repositories.db_manager import get_db_connection


# --- [1:1 고객 문의(Inquiry) 관리] ---

def insert_inquiry(user_id: int, category: str, title: str, content: str) -> bool:
    """사용자의 1:1 문의 내용을 DB에 저장합니다."""
    conn = get_db_connection()
    if not conn: return False

    try:
        with conn.cursor() as cur:
            query = """
                INSERT INTO inquiries (user_id, category, title, content)
                VALUES (%s, %s, %s, %s);
            """
            cur.execute(query, (user_id, category, title, content))
            conn.commit()  # 데이터 변경이 일어나는 INSERT 문이므로 반드시 commit 호출
            return True

    except Exception as e:
        print(f"❌ 문의 등록 중 에러 발생: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_inquiry_by_id(inquiry_id: int) -> Optional[Dict[str, Any]]:
    """특정 문의글 1개의 상세 정보를 딕셔너리 형태로 가져옵니다."""
    conn = get_db_connection()
    if not conn: return None

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM inquiries WHERE inquiry_id = %s;", (inquiry_id,))
            return cur.fetchone()
    except Exception as e:
        print(f"❌ 문의글 상세 조회 에러: {e}")
        return None
    finally:
        conn.close()


def update_inquiry_reply(inquiry_id: int, reply_content: str) -> bool:
    """
    관리자가 작성한 답변을 DB에 업데이트하고,
    해당 문의의 상태(status)를 해결됨(RESOLVED)으로 변경합니다.
    """
    conn = get_db_connection()
    if not conn: return False

    try:
        with conn.cursor() as cur:
            query = """
                UPDATE inquiries 
                SET reply_content = %s, 
                    replied_at = CURRENT_TIMESTAMP, 
                    status = 'RESOLVED'
                WHERE inquiry_id = %s;
            """
            cur.execute(query, (reply_content, inquiry_id))
            conn.commit()
            return True
    except Exception as e:
        print(f"❌ 답변 업데이트 에러: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_user_inquiries(user_id: int) -> List[Dict[str, Any]]:
    """특정 유저가 작성한 모든 문의 내역과 답변 여부를 최신순으로 가져옵니다."""
    conn = get_db_connection()
    if not conn: return []

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            query = """
                SELECT 
                    inquiry_id, category, title, content, 
                    status, created_at, reply_content, replied_at 
                FROM inquiries 
                WHERE user_id = %s 
                ORDER BY created_at DESC;
            """
            cur.execute(query, (user_id,))
            return cur.fetchall()
    except Exception as e:
        print(f"❌ 문의 내역 전체 조회 에러: {e}")
        return []
    finally:
        conn.close()