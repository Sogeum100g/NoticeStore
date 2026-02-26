from typing import Optional, List, Dict, Any
from psycopg.rows import dict_row

# 공통 DB 커넥션 매니저 임포트
from repositories.db_manager import get_db_connection


# --- [폴더(Folder) CRUD 및 구조 관리] ---

def check_folder_depth(folder_id: int, user_id: int) -> int:
    """
    특정 폴더의 뎁스(Depth)를 확인합니다.
    0: 최상위 폴더 (parent_folder_id 가 NULL)
    1: 1단계 하위 폴더 (부모가 있음)
    """
    conn = get_db_connection()
    if not conn: return -1

    query = """
        SELECT parent_folder_id 
        FROM favorite_folders 
        WHERE folder_id = %s AND user_id = %s;
    """
    try:
        with conn.cursor() as cur:
            cur.execute(query, (folder_id, user_id))
            result = cur.fetchone()

            if not result:
                return -1  # 폴더가 존재하지 않거나 권한이 없음

            parent_id = result[0]
            if parent_id is None:
                return 0  # 최상위 폴더
            else:
                return 1  # 하위 폴더 (2-Depth 제한)
    finally:
        conn.close()


def create_favorite_folder(user_id: int, folder_name: str, parent_folder_id: Optional[int] = None) -> Optional[int]:
    """새로운 즐겨찾기 폴더를 생성하고 생성된 folder_id를 반환합니다."""
    conn = get_db_connection()
    if not conn: return None

    query = """
        INSERT INTO favorite_folders (user_id, folder_name, parent_folder_id)
        VALUES (%s, %s, %s)
        RETURNING folder_id;
    """
    try:
        with conn.cursor() as cur:
            cur.execute(query, (user_id, folder_name, parent_folder_id))
            folder_id = cur.fetchone()[0]
            conn.commit()
            return folder_id
    except Exception as e:
        print(f"❌ [DB 에러] 폴더 생성 실패: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


def update_favorite_folder_name(folder_id: int, user_id: int, new_name: str) -> bool:
    """폴더의 이름을 변경합니다."""
    conn = get_db_connection()
    if not conn: return False

    query = """
        UPDATE favorite_folders
        SET folder_name = %s
        WHERE folder_id = %s AND user_id = %s;
    """
    try:
        with conn.cursor() as cur:
            cur.execute(query, (new_name, folder_id, user_id))
            success = cur.rowcount > 0
            conn.commit()
            return success
    except Exception as e:
        print(f"❌ [DB 에러] 폴더 이름 변경 실패: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def delete_favorite_folder(folder_id: int, user_id: int) -> bool:
    """
    폴더를 삭제합니다.
    DB 설계 시 ON DELETE CASCADE가 설정되어 있다면 하위 폴더 및 매핑 데이터가 자동 삭제됩니다.
    """
    conn = get_db_connection()
    if not conn: return False

    query = """
        DELETE FROM favorite_folders
        WHERE folder_id = %s AND user_id = %s;
    """
    try:
        with conn.cursor() as cur:
            cur.execute(query, (folder_id, user_id))
            success = cur.rowcount > 0
            conn.commit()
            return success
    except Exception as e:
        print(f"❌ [DB 에러] 폴더 삭제 실패: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def update_favorite_folder_order(user_id: int, ordered_folder_ids: List[int]) -> bool:
    """
    폴더의 정렬 순서(sort_order)를 클라이언트가 보낸 배열의 인덱스에 맞춰 일괄 업데이트합니다.
    """
    conn = get_db_connection()
    if not conn: return False

    query = """
        UPDATE favorite_folders
        SET sort_order = %s
        WHERE folder_id = %s AND user_id = %s;
    """
    try:
        with conn.cursor() as cur:
            for index, folder_id in enumerate(ordered_folder_ids):
                cur.execute(query, (index, folder_id, user_id))

            # 모든 쿼리가 성공했을 때만 최종 커밋 (원자성 보장)
            conn.commit()
            return True
    except Exception as e:
        print(f"❌ [DB 에러] 폴더 순서 업데이트 실패: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_favorite_folders_tree(user_id: int) -> List[Dict[str, Any]]:
    """
    유저의 전체 즐겨찾기 폴더, 공지사항, 키워드를 2-Depth 트리 구조로 조립하여 반환합니다.
    데이터베이스 통신 횟수를 최소화하고 애플리케이션 메모리에서 $O(N)$ 시간 복잡도로 트리를 구성합니다.
    """
    conn = get_db_connection()
    if not conn: return []

    folder_query = """
        SELECT folder_id, parent_folder_id, folder_name, sort_order
        FROM favorite_folders
        WHERE user_id = %s
        ORDER BY sort_order ASC, created_at ASC;
    """
    notice_query = """
        SELECT fn.folder_id, n.notice_id, n.title, n.url, n.site_id, n.created_at
        FROM favorite_notices fn
        JOIN notices n ON fn.notice_id = n.notice_id
        JOIN favorite_folders ff ON fn.folder_id = ff.folder_id
        WHERE ff.user_id = %s;
    """
    keyword_query = """
        SELECT fk.folder_id, fk.keyword
        FROM folder_keywords fk
        JOIN favorite_folders ff ON fk.folder_id = ff.folder_id
        WHERE ff.user_id = %s;
    """

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(folder_query, (user_id,))
            folders_raw = cur.fetchall()

            cur.execute(notice_query, (user_id,))
            notices_raw = cur.fetchall()

            cur.execute(keyword_query, (user_id,))
            keywords_raw = cur.fetchall()
    finally:
        conn.close()

    # --- [데이터 조립 (Adjacency List 방식)] ---
    folder_map = {}
    for row in folders_raw:
        folder_map[row['folder_id']] = {
            "folder_id": row['folder_id'],
            "parent_folder_id": row['parent_folder_id'],
            "folder_name": row['folder_name'],
            "sub_folders": [],
            "notices": [],
            "keywords": []
        }

    for row in notices_raw:
        f_id = row['folder_id']
        if f_id in folder_map:
            folder_map[f_id]['notices'].append({
                "notice_id": row['notice_id'],
                "title": row['title'],
                "url": row['url'],
                "site_id": row['site_id'],
                "created_at": row['created_at'].isoformat() if row['created_at'] else ""
            })

    for row in keywords_raw:
        f_id = row['folder_id']
        if f_id in folder_map:
            folder_map[f_id]['keywords'].append(row['keyword'])

    tree = []
    for f_id, folder_data in folder_map.items():
        parent_id = folder_data['parent_folder_id']
        if parent_id is None:
            tree.append(folder_data)
        else:
            if parent_id in folder_map:
                folder_map[parent_id]['sub_folders'].append(folder_data)

    return tree


# --- [폴더 내 공지사항(Notice) 매핑 관리] ---

def add_notice_to_folder(folder_id: int, user_id: int, notice_id: int) -> bool:
    """특정 폴더에 개별 공지사항을 추가(매핑)합니다."""
    conn = get_db_connection()
    if not conn: return False

    query = """
        INSERT INTO favorite_notices (folder_id, notice_id)
        SELECT %s, %s
        WHERE EXISTS (
            SELECT 1 FROM favorite_folders WHERE folder_id = %s AND user_id = %s
        )
        ON CONFLICT (folder_id, notice_id) DO NOTHING;
    """
    try:
        with conn.cursor() as cur:
            cur.execute(query, (folder_id, notice_id, folder_id, user_id))
            success = cur.rowcount > 0
            conn.commit()
            return success
    except Exception as e:
        print(f"❌ [DB 에러] 공지 추가 실패: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def remove_notice_from_folder(folder_id: int, user_id: int, notice_id: int) -> bool:
    """특정 폴더에서 공지사항을 제거(매핑 해제)합니다."""
    conn = get_db_connection()
    if not conn: return False

    query = """
        DELETE FROM favorite_notices fn
        USING favorite_folders ff
        WHERE fn.folder_id = ff.folder_id 
          AND fn.folder_id = %s 
          AND fn.notice_id = %s 
          AND ff.user_id = %s;
    """
    try:
        with conn.cursor() as cur:
            cur.execute(query, (folder_id, notice_id, user_id))
            success = cur.rowcount > 0
            conn.commit()
            return success
    except Exception as e:
        print(f"❌ [DB 에러] 공지 제거 실패: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


# --- [폴더별 키워드(Keyword) 자동 분류 관리] ---

def add_folder_keyword(folder_id: int, user_id: int, keyword: str) -> bool:
    """특정 즐겨찾기 폴더에 자동 분류를 위한 키워드를 추가합니다."""
    conn = get_db_connection()
    if not conn: return False

    query = """
        INSERT INTO folder_keywords (folder_id, keyword)
        SELECT %s, %s
        WHERE EXISTS (
            SELECT 1 FROM favorite_folders WHERE folder_id = %s AND user_id = %s
        )
        ON CONFLICT (folder_id, keyword) DO NOTHING;
    """
    try:
        with conn.cursor() as cur:
            cur.execute(query, (folder_id, keyword, folder_id, user_id))
            success = cur.rowcount > 0
            conn.commit()
            return success
    except Exception as e:
        print(f"❌ [DB 에러] 폴더 키워드 추가 실패: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def remove_folder_keyword(folder_id: int, user_id: int, keyword: str) -> bool:
    """특정 즐겨찾기 폴더에서 키워드를 삭제합니다."""
    conn = get_db_connection()
    if not conn: return False

    query = """
        DELETE FROM folder_keywords fk
        USING favorite_folders ff
        WHERE fk.folder_id = ff.folder_id 
          AND fk.folder_id = %s 
          AND fk.keyword = %s 
          AND ff.user_id = %s;
    """
    try:
        with conn.cursor() as cur:
            cur.execute(query, (folder_id, keyword, user_id))
            success = cur.rowcount > 0
            conn.commit()
            return success
    except Exception as e:
        print(f"❌ [DB 에러] 폴더 키워드 삭제 실패: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()