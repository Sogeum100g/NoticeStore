import asyncio
import datetime
import unittest
from pathlib import Path
from unittest.mock import patch

from repositories.notice_repo import (
    activate_site_after_successful_sync,
    get_all_user_notices,
    get_user_specific_sites,
    update_user_view_time,
)
from routers.notice_router import read_notices


class _Cursor:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executions = []
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=None):
        self.executions.append((query, params))

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, cursor):
        self.test_cursor = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self, **kwargs):
        return self.test_cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class SubscriptionUnreadRepositoryTests(unittest.TestCase):
    def test_folder_unread_status_uses_last_viewed_time(self):
        cursor = _Cursor()
        connection = _Connection(cursor)

        with patch(
            "repositories.notice_repo.get_db_connection",
            return_value=connection,
        ):
            get_user_specific_sites(9)

        query, params = cursor.executions[0]
        self.assertIn("n.created_at > us.last_viewed_at", query)
        self.assertIn("n.is_active = true", query)
        self.assertNotIn("n.created_at > us.last_synced_at", query)
        self.assertEqual(params, (9,))

    def test_each_notice_contains_user_specific_new_state(self):
        cursor = _Cursor()
        connection = _Connection(cursor)

        with patch(
            "repositories.notice_repo.get_db_connection",
            return_value=connection,
        ):
            get_all_user_notices(9)

        query, params = cursor.executions[0]
        self.assertIn("n.created_at > us.last_viewed_at", query)
        self.assertIn(") AS is_new", query)
        self.assertIn("registration_completed_at IS NOT NULL", query)
        self.assertEqual(params, (9, 9))

    def test_opening_folder_updates_only_view_baseline(self):
        cursor = _Cursor()
        connection = _Connection(cursor)

        with patch(
            "repositories.notice_repo.get_db_connection",
            return_value=connection,
        ):
            update_user_view_time(42, 9)

        query, params = cursor.executions[0]
        self.assertIn("last_viewed_at = NOW()", query)
        self.assertNotIn("last_synced_at = NOW()", query)
        self.assertEqual(params, (42, 9))
        self.assertTrue(connection.committed)

    def test_initial_sync_preserves_view_baseline_for_new_badges(self):
        cursor = _Cursor()
        connection = _Connection(cursor)

        with patch(
            "repositories.notice_repo.get_db_connection",
            return_value=connection,
        ):
            activate_site_after_successful_sync(42)

        baseline_query, params = cursor.executions[0]
        self.assertIn("last_synced_at = NOW()", baseline_query)
        self.assertNotIn("last_viewed_at = NOW()", baseline_query)
        self.assertIn("registration_completed_at = NOW()", baseline_query)
        self.assertEqual(params, (42,))
        self.assertTrue(connection.committed)

    def test_migration_preserves_existing_read_baseline(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20260824_add_subscription_view_state.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("ADD COLUMN IF NOT EXISTS last_viewed_at", migration)
        self.assertIn(
            "COALESCE(last_synced_at, created_at, CURRENT_TIMESTAMP)",
            migration,
        )
        self.assertIn("ALTER COLUMN last_viewed_at SET NOT NULL", migration)


class NoticeUnreadResponseTests(unittest.TestCase):
    def test_notice_api_exposes_is_new_for_each_card(self):
        timestamp = datetime.datetime(2026, 8, 24, tzinfo=datetime.timezone.utc)
        published_at = datetime.datetime(2026, 8, 20, tzinfo=datetime.timezone.utc)
        rows = [
            {
                "notice_id": 101,
                "title": "새 공지",
                "author": "기관",
                "url": "https://public.example/notices/101",
                "published_at": published_at,
                "created_at": timestamp,
                "scraped_at": timestamp,
                "site_id": 42,
                "is_new": True,
            }
        ]

        with patch("routers.notice_router.get_all_user_notices", return_value=rows):
            response = asyncio.run(read_notices(user_id=9))

        self.assertTrue(response["notices"][0]["is_new"])
        self.assertEqual(
            response["notices"][0]["published_at"],
            "2026-08-20T00:00:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()
