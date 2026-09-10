import asyncio
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from celery_app import process_notification_event
from repositories.notification_repo import create_notification_events_with_cursor
from repositories.notice_repo import persist_verified_extraction
from routers.subscription_router import change_subscription_notification
from schemas import SubscriptionNotificationRequest


class _Cursor:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executions = []
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=None):
        self.executions.append((query, params))

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows


class _Connection:
    def __init__(self):
        self.cursor_instance = _Cursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, **kwargs):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def _notice(external_id: str):
    return {
        "title": f"공지 {external_id}",
        "author": "기관",
        "url": "https://public.example/notices",
        "detail_url": f"https://public.example/notices/{external_id}",
        "external_id": external_id,
        "published_at": "2026-09-03",
        "scraped_at": "2026-09-03T00:00:00+00:00",
    }


class NotificationEventCreationTests(unittest.TestCase):
    def test_no_new_notice_creates_no_event(self):
        cursor = _Cursor()
        result = create_notification_events_with_cursor(
            cursor,
            site_id=42,
            crawl_run_id=7,
            new_notice_ids=[],
        )
        self.assertEqual(result, [])
        self.assertEqual(cursor.executions, [])

    def test_event_query_excludes_initial_and_disabled_subscriptions(self):
        cursor = _Cursor(rows=[(501,), (502,)])
        result = create_notification_events_with_cursor(
            cursor,
            site_id=42,
            crawl_run_id=7,
            new_notice_ids=[101, 102, 102],
        )

        self.assertEqual(result, [501, 502])
        event_query, event_params = cursor.executions[0]
        self.assertIn("registration_completed_at IS NOT NULL", event_query)
        self.assertIn("us.notification_enabled = TRUE", event_query)
        self.assertIn("u.is_notification_enabled = TRUE", event_query)
        self.assertNotIn("last_viewed_at", event_query)
        self.assertIn("ON CONFLICT (subscription_id, crawl_run_id)", event_query)
        self.assertEqual(event_params[2], [101, 102])
        self.assertEqual(event_params[3], 2)
        self.assertIn("user_fcm_tokens", cursor.executions[1][0])

    def test_persistence_batches_only_actual_inserts_before_activation(self):
        connection = _Connection()
        order = []
        kwargs = {
            "site_id": 42,
            "method_type": "GET",
            "api_url": "https://public.example/notices.json",
            "headers": {},
            "payload": {},
            "source_hash": "hash",
            "notices": [_notice("1"), _notice("2")],
            "processing_status": "success",
            "crawl_run_id": 7,
        }

        with (
            patch("repositories.notice_repo.get_db_connection", return_value=connection),
            patch("repositories.notice_repo._upsert_api_for_site_with_cursor", return_value=9),
            patch(
                "repositories.notice_repo._insert_or_update_notice_result_with_cursor",
                side_effect=[(101, False), (102, True)],
            ),
            patch(
                "repositories.notice_repo.create_notification_events_with_cursor",
                side_effect=lambda *args, **kw: order.append("event") or [501],
            ) as create_events,
            patch(
                "repositories.notice_repo._activate_site_after_successful_sync_with_cursor",
                side_effect=lambda *args: order.append("activate"),
            ),
        ):
            result = persist_verified_extraction(**kwargs)

        self.assertEqual(result["new_notice_ids"], [102])
        self.assertEqual(result["new_notice_count"], 1)
        self.assertEqual(result["notification_event_ids"], [501])
        self.assertEqual(order, ["event", "activate"])
        self.assertEqual(create_events.call_args.kwargs["new_notice_ids"], [102])
        self.assertEqual(connection.commits, 1)


class SubscriptionNotificationApiTests(unittest.TestCase):
    def test_subscription_toggle_updates_owned_site(self):
        with patch(
            "routers.subscription_router.update_subscription_notification",
            return_value=True,
        ) as update:
            result = asyncio.run(
                change_subscription_notification(
                    42,
                    SubscriptionNotificationRequest(notification_enabled=True),
                    user_id=9,
                )
            )

        update.assert_called_once_with(9, 42, True)
        self.assertTrue(result["notification_enabled"])


class NotificationDeliveryTaskTests(unittest.TestCase):
    def test_event_sends_one_summary_to_each_pending_device(self):
        event = {
            "event_id": 501,
            "site_id": 42,
            "alias": "학교 공지",
            "new_notice_count": 3,
            "notification_enabled": True,
            "is_notification_enabled": True,
        }
        deliveries = [
            {"delivery_id": 1, "token_id": 11, "fcm_token": "a", "attempt_count": 0},
            {"delivery_id": 2, "token_id": 12, "fcm_token": "b", "attempt_count": 0},
        ]
        with (
            patch("celery_app.claim_notification_event", return_value=event),
            patch("celery_app.get_ready_deliveries", return_value=deliveries),
            patch("celery_app.send_fcm_notification", return_value=True) as send,
            patch("celery_app.mark_delivery_sent") as mark_sent,
            patch("celery_app.finish_notification_event", return_value=False),
        ):
            result = process_notification_event.run(501)

        self.assertEqual(result["status"], "complete")
        self.assertEqual(send.call_count, 2)
        self.assertEqual(mark_sent.call_count, 2)
        self.assertEqual(
            send.call_args.kwargs["body"],
            "'학교 공지'에 새 소식 3건이 도착했습니다.",
        )
        self.assertEqual(send.call_args.kwargs["data"]["site_id"], 42)

    def test_global_master_off_cancels_without_sending(self):
        event = {
            "event_id": 501,
            "site_id": 42,
            "alias": "학교 공지",
            "new_notice_count": 1,
            "notification_enabled": True,
            "is_notification_enabled": False,
        }
        with (
            patch("celery_app.claim_notification_event", return_value=event),
            patch("celery_app.cancel_notification_event") as cancel,
            patch("celery_app.send_fcm_notification") as send,
        ):
            result = process_notification_event.run(501)

        self.assertEqual(result["status"], "cancelled")
        cancel.assert_called_once_with(501)
        send.assert_not_called()


class NotificationMigrationTests(unittest.TestCase):
    def test_migration_defaults_existing_subscriptions_to_off(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20260903_add_subscription_notifications.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("notification_enabled BOOLEAN NOT NULL DEFAULT FALSE", migration)
        self.assertIn("subscription_notification_events", migration)
        self.assertIn("subscription_notification_deliveries", migration)
        self.assertIn("DROP COLUMN IF EXISTS notification_time", migration)


if __name__ == "__main__":
    unittest.main()
