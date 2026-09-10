import unittest
from unittest.mock import patch

from repositories.notice_repo import (
    activate_site_after_successful_sync,
    add_user_subscription,
    record_site_submission,
)
from dataController.scraper.scrape_auto import _complete_structured_processing


class _Cursor:
    def __init__(self, *, rows=None, rowcount=1):
        self.rows = rows or []
        self.rowcount = rowcount
        self.executions = []

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


class RegistrationNotificationBaselineTests(unittest.TestCase):
    def test_new_attempt_resets_stale_failure_but_preserves_active_site(self):
        cursor = _Cursor()
        connection = _Connection(cursor)

        with patch(
            "repositories.notice_repo.get_db_connection",
            return_value=connection,
        ):
            record_site_submission(
                42,
                submitted_url="https://public.example/notices",
            )

        query, params = cursor.executions[0]
        self.assertIn("WHEN crawl_status = 'active' THEN 'active'", query)
        self.assertIn("ELSE 'pending'", query)
        self.assertIn("validation_error_code = NULL", query)
        self.assertEqual(
            params,
            ("https://public.example/notices", "valid", 42),
        )
        self.assertTrue(connection.committed)

    def test_pending_subscription_is_inserted_without_opening_notifications(self):
        cursor = _Cursor()
        connection = _Connection(cursor)

        with patch(
            "repositories.notice_repo.get_db_connection",
            return_value=connection,
        ):
            result = add_user_subscription(9, 42, "학교 공지")

        self.assertTrue(result)
        query, params = cursor.executions[0]
        self.assertIn("registration_completed_at", query)
        self.assertIn("crawl_status", query)
        self.assertIn("ELSE NULL", query)
        self.assertEqual(params, (9, "학교 공지", 42))
        self.assertTrue(connection.committed)

    def test_successful_sync_atomically_opens_notifications_and_activates_site(self):
        cursor = _Cursor()
        connection = _Connection(cursor)

        with patch(
            "repositories.notice_repo.get_db_connection",
            return_value=connection,
        ):
            activate_site_after_successful_sync(42)

        baseline_query, baseline_params = cursor.executions[0]
        activation_query, activation_params = cursor.executions[1]
        self.assertIn("last_synced_at = NOW()", baseline_query)
        self.assertNotIn("last_viewed_at = NOW()", baseline_query)
        self.assertIn("registration_completed_at = NOW()", baseline_query)
        self.assertIn("registration_completed_at IS NULL", baseline_query)
        self.assertEqual(baseline_params, (42,))
        self.assertIn("crawl_status = 'active'", activation_query)
        self.assertIn("validation_status = 'valid'", activation_query)
        self.assertEqual(activation_params, (42,))
        self.assertTrue(connection.committed)

    def test_successful_sync_rolls_back_both_states_when_activation_fails(self):
        class _FailingCursor(_Cursor):
            def execute(self, query, params=None):
                super().execute(query, params)
                if "UPDATE sites" in query:
                    raise RuntimeError("site update failed")

        cursor = _FailingCursor()
        connection = _Connection(cursor)

        with patch(
            "repositories.notice_repo.get_db_connection",
            return_value=connection,
        ):
            with self.assertRaises(RuntimeError):
                activate_site_after_successful_sync(42)

        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)

    def test_failed_initial_sync_does_not_open_notification_gate(self):
        with (
            patch(
                "dataController.scraper.scrape_auto.notice_repo."
                "update_api_processing_state",
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo."
                "update_site_crawl_state",
            ) as update_site_state,
            patch(
                "dataController.scraper.scrape_auto.notice_repo."
                "activate_site_after_successful_sync",
            ) as activate_site,
            patch(
                "dataController.scraper.scrape_auto.notice_repo.finish_crawl_run",
            ),
        ):
            result = _complete_structured_processing(
                api={"_pending_persistence": False},
                target_url="https://public.example/notices",
                site_id=42,
                api_url="https://public.example/notices.json",
                new_hash="failed-hash",
                structured={
                    "status": "error",
                    "notices": [],
                    "error_msg": "extract failed",
                },
                crawl_run_id=7,
            )

        self.assertEqual(result, "failed")
        activate_site.assert_not_called()
        update_site_state.assert_called_once_with(
            42,
            crawl_status="failed",
            validation_error_code="NOTICE_EXTRACTION_FAILED",
            validation_error="extract failed",
        )

if __name__ == "__main__":
    unittest.main()
