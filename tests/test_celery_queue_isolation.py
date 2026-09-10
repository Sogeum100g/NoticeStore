import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import yaml

from celery_app import (
    CRAWL_QUEUE,
    NOTIFICATION_QUEUE,
    celery_app,
    scrape_target_site,
)


class CeleryQueueRoutingTests(unittest.TestCase):
    def test_known_tasks_are_routed_to_dedicated_queues(self):
        expected_routes = {
            "celery_app.dispatch_all_sites": CRAWL_QUEUE,
            "celery_app.scrape_target_site": CRAWL_QUEUE,
            "celery_app.dispatch_pending_notification_events": NOTIFICATION_QUEUE,
            "celery_app.process_notification_event": NOTIFICATION_QUEUE,
        }

        for task_name, expected_queue in expected_routes.items():
            with self.subTest(task=task_name):
                route = celery_app.amqp.router.route(
                    {},
                    task_name,
                    args=(),
                    kwargs={},
                )
                self.assertEqual(route["queue"].name, expected_queue)
                self.assertEqual(route["queue"].exchange.name, expected_queue)
                self.assertEqual(route["queue"].routing_key, expected_queue)
                self.assertEqual(route["routing_key"], expected_queue)

    def test_beat_jobs_publish_to_their_dedicated_queues(self):
        schedule = celery_app.conf.beat_schedule

        self.assertEqual(
            schedule["scrape-subscribed-sites-3-times-a-day"]["options"]["queue"],
            CRAWL_QUEUE,
        )
        self.assertEqual(
            schedule["recover-pending-notification-events-every-minute"]["options"]["queue"],
            NOTIFICATION_QUEUE,
        )
        self.assertNotIn("check-and-send-notifications-every-minute", schedule)

    def test_scrape_task_preserves_registration_site_id(self):
        with patch(
            "celery_app.run_full_scrape",
            new=AsyncMock(
                return_value={
                    "status": "error",
                    "site_id": 42,
                    "notices": [],
                }
            ),
        ) as run_scrape:
            result = scrape_target_site.run(
                42,
                "https://short.example/redirect",
            )

        run_scrape.assert_awaited_once_with(
            "https://short.example/redirect",
            site_id=42,
        )
        self.assertEqual(result["site_id"], 42)


class ComposeWorkerIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compose_path = Path(__file__).resolve().parents[1] / "docker-compose.yml"
        cls.services = yaml.safe_load(compose_path.read_text(encoding="utf-8"))[
            "services"
        ]

    def test_crawler_worker_only_consumes_crawl_queue(self):
        command = self.services["crawler_worker"]["command"]

        self.assertIn("--queues=crawl", command)
        self.assertIn("--concurrency=2", command)
        self.assertIn("--prefetch-multiplier=1", command)

    def test_notification_worker_only_consumes_notification_queue(self):
        command = self.services["notification_worker"]["command"]

        self.assertIn("--queues=notification", command)
        self.assertIn("--concurrency=2", command)

    def test_unscoped_worker_was_removed(self):
        self.assertNotIn("celery_worker", self.services)


if __name__ == "__main__":
    unittest.main()
