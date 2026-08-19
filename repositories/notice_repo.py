import datetime
import psycopg
from typing import Optional, List, Dict, Any
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

# 공통 DB 커넥션 매니저 임포트
from repositories.db_manager import get_db_connection

# --- [1. 사이트(Site) 및 크롤링 API 관리] ---

def insert_site(
    site_url: str,
    created_at: datetime.datetime,
    *,
    submitted_url: Optional[str] = None,
    crawl_status: str = "pending",
    validation_status: Optional[str] = None,
    validation_error: Optional[str] = None,
) -> Optional[int]:
    """새로운 사이트를 등록하고 생성된 site_id를 반환합니다."""
    conn = get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            query = """
                INSERT INTO sites (
                    site_url, created_at, submitted_url, crawl_status,
                    validation_status, validation_error, last_validated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (site_url)
                DO UPDATE SET
                    submitted_url = COALESCE(sites.submitted_url, EXCLUDED.submitted_url)
                RETURNING site_id;
            """
            cur.execute(
                query,
                (
                    site_url,
                    created_at,
                    submitted_url or site_url,
                    crawl_status,
                    validation_status,
                    validation_error,
                ),
            )
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


def upsert_api_for_site(
    site_id: int,
    method_type: str,
    api_url: str,
    headers: dict,
    payload: dict,
    last_hash: str,
    extractor_config: Optional[dict] = None,
    schema_hash: Optional[str] = None,
    processing_status: Optional[str] = None,
    extractor_confidence: Optional[float] = None,
) -> Optional[int]:
    """사이트의 검증 완료 API를 저장하고 기존 오답 설정이 있으면 교체합니다."""
    conn = get_db_connection()
    if not conn or not site_id:
        return None
    try:
        with conn.cursor() as cur:
            update_query = """
                UPDATE api
                SET method_type = %s,
                    api_url = %s,
                    headers = %s,
                    payload = %s,
                    last_hash = %s,
                    extractor_config = COALESCE(%s, extractor_config),
                    schema_hash = COALESCE(%s, schema_hash),
                    processing_status = COALESCE(%s, processing_status),
                    extractor_confidence = COALESCE(%s, extractor_confidence),
                    scraped_at = NOW()
                WHERE site_id = %s
                RETURNING api_id;
            """
            cur.execute(
                update_query,
                (
                    method_type,
                    api_url,
                    Jsonb(headers or {}),
                    Jsonb(payload or {}),
                    last_hash,
                    Jsonb(extractor_config) if extractor_config is not None else None,
                    schema_hash,
                    processing_status,
                    extractor_confidence,
                    site_id,
                ),
            )
            updated = cur.fetchone()
            if updated:
                conn.commit()
                return updated[0]

            insert_query = """
                INSERT INTO api (
                    site_id, method_type, api_url, headers, payload,
                    created_at, scraped_at, last_hash, extractor_config,
                    schema_hash, processing_status, extractor_confidence
                )
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW(), %s, %s, %s, %s, %s)
                RETURNING api_id;
            """
            cur.execute(
                insert_query,
                (
                    site_id,
                    method_type,
                    api_url,
                    Jsonb(headers or {}),
                    Jsonb(payload or {}),
                    last_hash,
                    Jsonb(extractor_config) if extractor_config is not None else None,
                    schema_hash,
                    processing_status,
                    extractor_confidence,
                ),
            )
            inserted = cur.fetchone()
            conn.commit()
            return inserted[0] if inserted else None
    except Exception as e:
        print(f"API 설정 upsert 중 에러 발생: {e}")
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
                    last_observed_hash = %s,
                    last_processed_hash = %s,
                    processing_status = 'success',
                    retry_count = 0,
                    next_retry_at = NULL,
                    last_error = NULL,
                    scraped_at = NOW()
                WHERE api_url = %s;
            """
            cur.execute(query, (last_hash, last_hash, last_hash, api_url))
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
                SELECT s.site_id, a.api_id, a.method_type, a.api_url,
                       a.headers, a.payload, a.created_at, a.extractor_config,
                       a.schema_hash, a.last_observed_hash,
                       a.last_processed_hash, a.processing_status,
                       a.retry_count, a.next_retry_at
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


def select_processing_state(url: str) -> Dict[str, Any]:
    """Return the split observation/processing cache state for one API."""
    conn = get_db_connection()
    if not conn:
        return {}
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT api_id, last_hash, last_observed_hash,
                       last_processed_hash, processing_status,
                       retry_count, next_retry_at, last_error
                FROM api
                WHERE api_url = %s;
                """,
                (url,),
            )
            return cur.fetchone() or {}
    finally:
        conn.close()


def update_api_processing_state(
    api_url: str,
    *,
    observed_hash: str,
    status: str,
    processed_hash: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Persist success, valid-empty, or failed without conflating their hashes."""
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            if status == "failed":
                cur.execute(
                    """
                    UPDATE api
                    SET last_observed_hash = %s,
                        processing_status = 'failed',
                        retry_count = retry_count + 1,
                        next_retry_at = NOW() + LEAST(
                            INTERVAL '24 hours',
                            INTERVAL '5 minutes' * POWER(2, LEAST(retry_count, 8))
                        ),
                        last_error = %s,
                        scraped_at = NOW()
                    WHERE api_url = %s;
                    """,
                    (observed_hash, error, api_url),
                )
            else:
                cur.execute(
                    """
                    UPDATE api
                    SET last_observed_hash = %s,
                        last_processed_hash = %s,
                        processing_status = %s,
                        retry_count = 0,
                        next_retry_at = NULL,
                        last_error = NULL,
                        scraped_at = NOW()
                    WHERE api_url = %s;
                    """,
                    (
                        observed_hash,
                        processed_hash or observed_hash,
                        status,
                        api_url,
                    ),
                )
            conn.commit()
    except Exception as exc:
        print(f"❌ API 처리 상태 업데이트 에러: {exc}")
        conn.rollback()
    finally:
        conn.close()


def update_api_extractor(
    api_url: str,
    *,
    extractor_config: Dict[str, Any],
    schema_hash: Optional[str],
    confidence: Optional[float],
) -> None:
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE api
                SET extractor_config = %s,
                    schema_hash = %s,
                    extractor_confidence = %s
                WHERE api_url = %s;
                """,
                (
                    Jsonb(extractor_config),
                    schema_hash,
                    confidence,
                    api_url,
                ),
            )
            conn.commit()
    except Exception as exc:
        print(f"❌ API 추출 규칙 업데이트 에러: {exc}")
        conn.rollback()
    finally:
        conn.close()


def update_site_crawl_state(
    site_id: int,
    *,
    crawl_status: str,
    validation_status: Optional[str] = None,
    validation_error: Optional[str] = None,
) -> None:
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sites
                SET crawl_status = %s,
                    validation_status = COALESCE(%s, validation_status),
                    validation_error = %s,
                    last_validated_at = NOW()
                WHERE site_id = %s;
                """,
                (crawl_status, validation_status, validation_error, site_id),
            )
            conn.commit()
    except Exception as exc:
        print(f"❌ 사이트 상태 업데이트 에러: {exc}")
        conn.rollback()
    finally:
        conn.close()


def record_site_submission(
    site_id: int,
    *,
    submitted_url: str,
    validation_status: str = "valid",
) -> None:
    """Dual-write the submitted URL without resetting an already active site."""
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sites
                SET submitted_url = %s,
                    crawl_status = COALESCE(crawl_status, 'pending'),
                    validation_status = %s,
                    validation_error = NULL,
                    last_validated_at = NOW()
                WHERE site_id = %s;
                """,
                (submitted_url, validation_status, site_id),
            )
            conn.commit()
    except Exception as exc:
        print(f"❌ 사이트 등록 정보 업데이트 에러: {exc}")
        conn.rollback()
    finally:
        conn.close()


def create_crawl_run(
    site_id: int,
    *,
    api_id: Optional[int] = None,
    status: str = "running",
    selection_mode: Optional[str] = None,
    processing_mode: Optional[str] = None,
    candidate_count: Optional[int] = None,
    selection_decision: Optional[str] = None,
    selection_reason: Optional[str] = None,
    selected_candidate_index: Optional[int] = None,
    candidate_evidence: Optional[List[Dict[str, Any]]] = None,
    llm_used: bool = False,
    llm_input_tokens: Optional[int] = None,
    llm_output_tokens: Optional[int] = None,
    llm_cost: Optional[float] = None,
) -> Optional[int]:
    conn = get_db_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO crawl_runs (
                    site_id, api_id, status, selection_mode, processing_mode,
                    candidate_count, selection_decision, selection_reason,
                    selected_candidate_index, candidate_evidence, llm_used,
                    llm_input_tokens, llm_output_tokens, llm_cost
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                RETURNING crawl_run_id;
                """,
                (
                    site_id,
                    api_id,
                    status,
                    selection_mode,
                    processing_mode,
                    candidate_count,
                    selection_decision,
                    selection_reason,
                    selected_candidate_index,
                    Jsonb(candidate_evidence or []),
                    llm_used,
                    llm_input_tokens,
                    llm_output_tokens,
                    llm_cost,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return row[0] if row else None
    except Exception as exc:
        print(f"❌ 크롤링 실행 이력 생성 에러: {exc}")
        conn.rollback()
        return None
    finally:
        conn.close()


def finish_crawl_run(
    crawl_run_id: Optional[int],
    *,
    status: str,
    observed_hash: Optional[str] = None,
    processed_hash: Optional[str] = None,
    schema_hash: Optional[str] = None,
    extracted_notice_count: Optional[int] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    llm_used: Optional[bool] = None,
    llm_input_tokens: Optional[int] = None,
    llm_output_tokens: Optional[int] = None,
    llm_cost: Optional[float] = None,
) -> None:
    if not crawl_run_id:
        return
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE crawl_runs
                SET status = %s,
                    observed_hash = %s,
                    processed_hash = %s,
                    schema_hash = %s,
                    extracted_notice_count = %s,
                    error_code = %s,
                    error_message = %s,
                    llm_used = COALESCE(%s, llm_used),
                    llm_input_tokens = COALESCE(%s, llm_input_tokens),
                    llm_output_tokens = COALESCE(%s, llm_output_tokens),
                    llm_cost = COALESCE(%s, llm_cost),
                    finished_at = NOW()
                WHERE crawl_run_id = %s;
                """,
                (
                    status,
                    observed_hash,
                    processed_hash,
                    schema_hash,
                    extracted_notice_count,
                    error_code,
                    error_message,
                    llm_used,
                    llm_input_tokens,
                    llm_output_tokens,
                    llm_cost,
                    crawl_run_id,
                ),
            )
            conn.commit()
    except Exception as exc:
        print(f"❌ 크롤링 실행 이력 완료 처리 에러: {exc}")
        conn.rollback()
    finally:
        conn.close()


def get_crawl_runs_for_review(
    *,
    reviewed: bool = False,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Return bounded, sanitized crawl telemetry for an admin review queue."""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        conditions = [
            "cr.review_label IS NOT NULL"
            if reviewed
            else "cr.review_label IS NULL"
        ]
        params: List[Any] = []
        if status:
            conditions.append("cr.status = %s")
            params.append(status)
        params.append(limit)

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT cr.crawl_run_id, cr.site_id, s.site_url,
                       cr.status, cr.selection_mode,
                       cr.selection_decision, cr.selection_reason,
                       cr.selected_candidate_index,
                       cr.candidate_count, cr.candidate_evidence,
                       cr.extracted_notice_count, cr.llm_used,
                       cr.llm_input_tokens, cr.llm_output_tokens,
                       cr.llm_cost, cr.error_code, cr.error_message,
                       cr.started_at, cr.finished_at,
                       cr.review_label, cr.review_notes,
                       cr.reviewed_by, cr.reviewed_at
                FROM crawl_runs cr
                JOIN sites s ON s.site_id = cr.site_id
                WHERE {" AND ".join(conditions)}
                ORDER BY cr.started_at DESC
                LIMIT %s;
                """,
                tuple(params),
            )
            return cur.fetchall()
    except Exception as exc:
        print(f"❌ 크롤링 검토 큐 조회 에러: {exc}")
        return []
    finally:
        conn.close()


def review_crawl_run(
    crawl_run_id: int,
    *,
    reviewer_id: int,
    label: str,
    review_notes: Optional[str] = None,
) -> bool:
    """Persist a human selection label for later calibration."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE crawl_runs
                SET review_label = %s,
                    review_notes = %s,
                    reviewed_by = %s,
                    reviewed_at = NOW()
                WHERE crawl_run_id = %s;
                """,
                (label, review_notes, reviewer_id, crawl_run_id),
            )
            updated = cur.rowcount > 0
            conn.commit()
            return updated
    except Exception as exc:
        print(f"❌ 크롤링 검토 결과 저장 에러: {exc}")
        conn.rollback()
        return False
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
                    END as has_new,
                    COALESCE(s.crawl_status, 'active') AS crawl_status,
                    s.validation_error
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


def get_user_site_status(user_id: int, site_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    if not conn:
        return None
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT s.site_id, s.site_url,
                       COALESCE(s.crawl_status, 'active') AS crawl_status,
                       s.validation_status, s.validation_error,
                       s.last_validated_at
                FROM sites s
                JOIN user_subscriptions us ON us.site_id = s.site_id
                WHERE us.user_id = %s AND s.site_id = %s;
                """,
                (user_id, site_id),
            )
            return cur.fetchone()
    except Exception as exc:
        print(f"사이트 상태 조회 중 오류: {exc}")
        return None
    finally:
        conn.close()

def add_user_subscription(user_id: int, site_id: int, alias: str) -> bool:
    """사용자의 구독 목록에 사이트를 추가합니다. 중복 시 별명(alias)만 갱신합니다."""
    conn = get_db_connection()
    if not conn: return False
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
            return True
    except Exception as e:
        conn.rollback()
        print(f"구독 추가 중 오류 발생: {e}")
        return False
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

def insert_notice(
    site_id: int,
    title: str,
    author: str,
    url: str,
    created_at: datetime.datetime,
    scraped_at: datetime.datetime,
) -> Optional[int]:
    """Compatibility wrapper using the valid (site_id, title) conflict key."""
    return insert_or_update_notice(
        site_id=site_id,
        title=title,
        author=author,
        url=url,
        created_at=created_at,
        scraped_at=scraped_at,
    )


def insert_or_update_notice(
    site_id: int,
    title: str,
    author: str,
    url: str,
    created_at: Optional[datetime.datetime],
    scraped_at: datetime.datetime,
    is_active: bool = True,
    *,
    detail_url: Optional[str] = None,
    external_id: Optional[str] = None,
    published_at: Optional[datetime.datetime] = None,
    content_type: Optional[str] = None,
    record_hash: Optional[str] = None,
) -> Optional[int]:
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
    clean_detail_url = detail_url.strip() if detail_url else None
    clean_external_id = str(external_id).strip() if external_id is not None else None

    try:
        with conn.cursor() as cur:
            existing_notice_id = None
            if clean_external_id:
                cur.execute(
                    """
                    SELECT notice_id FROM notices
                    WHERE site_id = %s AND external_id = %s;
                    """,
                    (site_id, clean_external_id),
                )
                row = cur.fetchone()
                existing_notice_id = row[0] if row else None
            if not existing_notice_id and clean_detail_url:
                cur.execute(
                    """
                    SELECT notice_id FROM notices
                    WHERE site_id = %s AND detail_url = %s;
                    """,
                    (site_id, clean_detail_url),
                )
                row = cur.fetchone()
                existing_notice_id = row[0] if row else None

            if existing_notice_id:
                cur.execute(
                    """
                    UPDATE notices
                    SET title = %s,
                        author = %s,
                        url = %s,
                        detail_url = COALESCE(%s, detail_url),
                        external_id = COALESCE(%s, external_id),
                        published_at = COALESCE(%s, published_at),
                        content_type = COALESCE(%s, content_type),
                        record_hash = COALESCE(%s, record_hash),
                        scraped_at = %s,
                        is_active = %s
                    WHERE notice_id = %s
                    RETURNING notice_id;
                    """,
                    (
                        clean_title,
                        clean_author,
                        clean_url,
                        clean_detail_url,
                        clean_external_id,
                        published_at,
                        content_type,
                        record_hash,
                        scraped_at,
                        is_active,
                        existing_notice_id,
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                return row[0] if row else existing_notice_id

            query = """
                INSERT INTO notices (
                    site_id, title, author, url, created_at, scraped_at, is_active,
                    detail_url, external_id, published_at, content_type, record_hash
                ) VALUES (%s, %s, %s, %s, COALESCE(%s, NOW()), %s, %s,
                          %s, %s, %s, %s, %s)
                ON CONFLICT (site_id, title) 
                DO UPDATE SET 
                    author = EXCLUDED.author,
                    url = EXCLUDED.url,
                    detail_url = COALESCE(EXCLUDED.detail_url, notices.detail_url),
                    external_id = COALESCE(EXCLUDED.external_id, notices.external_id),
                    published_at = COALESCE(EXCLUDED.published_at, notices.published_at),
                    content_type = COALESCE(EXCLUDED.content_type, notices.content_type),
                    record_hash = COALESCE(EXCLUDED.record_hash, notices.record_hash),
                    scraped_at = EXCLUDED.scraped_at,
                    is_active = EXCLUDED.is_active
                RETURNING notice_id;
            """
            cur.execute(
                query,
                (
                    site_id,
                    clean_title,
                    clean_author,
                    clean_url,
                    created_at,
                    scraped_at,
                    is_active,
                    clean_detail_url,
                    clean_external_id,
                    published_at,
                    content_type,
                    record_hash,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return row[0] if row else None
    except Exception as e:
        print(f"❌ 데이터 저장/업데이트 중 에러 발생: {e}")
        conn.rollback()
        return None
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
                SELECT n.notice_id, n.title, n.author,
                       COALESCE(n.detail_url, n.url) AS url,
                       n.created_at, n.scraped_at
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
                SELECT n.notice_id, n.title, n.author,
                       COALESCE(n.detail_url, n.url) AS url,
                       n.created_at, n.scraped_at, n.site_id,
                       n.published_at
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
