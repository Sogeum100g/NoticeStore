from typing import Any, Dict, List, Optional

from psycopg.rows import dict_row

from repositories.db_manager import get_db_connection


MAX_DELIVERY_ATTEMPTS = 3


def create_notification_events_with_cursor(
    cur,
    *,
    site_id: int,
    crawl_run_id: Optional[int],
    new_notice_ids: List[int],
) -> List[int]:
    """Create one durable event per eligible subscription in the caller transaction.

    This must run before pending subscriptions are activated. That ordering keeps
    the first historical import out of the notification stream.
    """
    unique_notice_ids = list(dict.fromkeys(new_notice_ids))
    if not crawl_run_id or not unique_notice_ids:
        return []

    cur.execute(
        """
        INSERT INTO subscription_notification_events (
            subscription_id, crawl_run_id, site_id,
            new_notice_ids, new_notice_count
        )
        SELECT us.subscription_id, %s, %s, %s, %s
        FROM user_subscriptions us
        JOIN users u ON u.user_id = us.user_id
        WHERE us.site_id = %s
          AND us.registration_completed_at IS NOT NULL
          AND us.notification_enabled = TRUE
          AND u.is_notification_enabled = TRUE
        ON CONFLICT (subscription_id, crawl_run_id) DO NOTHING
        RETURNING event_id;
        """,
        (
            crawl_run_id,
            site_id,
            unique_notice_ids,
            len(unique_notice_ids),
            site_id,
        ),
    )
    event_ids = [row[0] for row in cur.fetchall()]
    if not event_ids:
        return []

    cur.execute(
        """
        INSERT INTO subscription_notification_deliveries (event_id, token_id)
        SELECT e.event_id, t.token_id
        FROM subscription_notification_events e
        JOIN user_subscriptions us
          ON us.subscription_id = e.subscription_id
        JOIN user_fcm_tokens t ON t.user_id = us.user_id
        WHERE e.event_id = ANY(%s)
        ON CONFLICT (event_id, token_id) DO NOTHING;
        """,
        (event_ids,),
    )
    return event_ids


def get_pending_event_ids(limit: int = 100) -> List[int]:
    conn = get_db_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_id
                FROM subscription_notification_events
                WHERE status = 'pending'
                   OR (
                       status = 'processing'
                       AND updated_at < NOW() - INTERVAL '10 minutes'
                   )
                ORDER BY created_at, event_id
                LIMIT %s;
                """,
                (limit,),
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def claim_notification_event(event_id: int) -> Optional[Dict[str, Any]]:
    """Claim an event and return its current subscription context."""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE subscription_notification_events
                SET status = 'processing', updated_at = NOW()
                WHERE event_id = %s
                  AND (
                      status = 'pending'
                      OR (
                          status = 'processing'
                          AND updated_at < NOW() - INTERVAL '10 minutes'
                      )
                  )
                RETURNING event_id;
                """,
                (event_id,),
            )
            if not cur.fetchone():
                conn.rollback()
                return None

            cur.execute(
                """
                SELECT e.event_id, e.site_id, e.new_notice_count,
                       us.alias, us.notification_enabled,
                       u.is_notification_enabled
                FROM subscription_notification_events e
                JOIN user_subscriptions us
                  ON us.subscription_id = e.subscription_id
                JOIN users u ON u.user_id = us.user_id
                WHERE e.event_id = %s;
                """,
                (event_id,),
            )
            context = cur.fetchone()
            conn.commit()
            return dict(context) if context else None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_ready_deliveries(event_id: int) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    if not conn:
        return []
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT d.delivery_id, d.token_id, d.attempt_count,
                       t.fcm_token
                FROM subscription_notification_deliveries d
                JOIN user_fcm_tokens t ON t.token_id = d.token_id
                WHERE d.event_id = %s
                  AND d.status IN ('pending', 'failed')
                  AND d.attempt_count < %s
                  AND d.next_attempt_at <= NOW()
                ORDER BY d.delivery_id;
                """,
                (event_id, MAX_DELIVERY_ATTEMPTS),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def mark_delivery_sent(delivery_id: int) -> None:
    _update_delivery(
        delivery_id,
        """
        status = 'sent', attempt_count = attempt_count + 1,
        sent_at = NOW(), last_error = NULL, updated_at = NOW()
        """,
    )


def mark_delivery_failed(delivery_id: int, error: str, delay_seconds: int) -> None:
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE subscription_notification_deliveries
                SET status = 'failed',
                    attempt_count = attempt_count + 1,
                    next_attempt_at = NOW() + (%s * INTERVAL '1 second'),
                    last_error = %s,
                    updated_at = NOW()
                WHERE delivery_id = %s;
                """,
                (delay_seconds, error[:2000], delivery_id),
            )
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_invalid_token(token_id: int) -> None:
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_fcm_tokens WHERE token_id = %s;", (token_id,))
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cancel_notification_event(event_id: int) -> None:
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE subscription_notification_deliveries
                SET status = 'cancelled', updated_at = NOW()
                WHERE event_id = %s AND status <> 'sent';
                """,
                (event_id,),
            )
            cur.execute(
                """
                UPDATE subscription_notification_events
                SET status = 'cancelled', completed_at = NOW(), updated_at = NOW()
                WHERE event_id = %s;
                """,
                (event_id,),
            )
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def finish_notification_event(event_id: int) -> bool:
    """Finalize terminal events; return True when retryable work remains."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'sent') AS sent,
                       COUNT(*) FILTER (
                           WHERE status IN ('pending', 'failed')
                             AND attempt_count < %s
                       ) AS retryable
                FROM subscription_notification_deliveries
                WHERE event_id = %s;
                """,
                (MAX_DELIVERY_ATTEMPTS, event_id),
            )
            counts = cur.fetchone()
            retryable = bool(counts and counts["retryable"])
            if retryable:
                status = "pending"
                completed_at = None
            else:
                status = "sent" if counts and counts["sent"] else "cancelled"
                completed_at = "NOW()"

            cur.execute(
                f"""
                UPDATE subscription_notification_events
                SET status = %s,
                    completed_at = {completed_at or 'NULL'},
                    updated_at = NOW()
                WHERE event_id = %s;
                """,
                (status, event_id),
            )
            conn.commit()
            return retryable
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _update_delivery(delivery_id: int, assignments: str) -> None:
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE subscription_notification_deliveries SET {assignments} "
                "WHERE delivery_id = %s;",
                (delivery_id,),
            )
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
