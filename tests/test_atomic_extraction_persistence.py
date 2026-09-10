import unittest
from unittest.mock import patch

from dataController.scraper.scrape_auto import _complete_structured_processing
from repositories.notice_repo import persist_verified_extraction


class _Cursor:
    def __init__(self):
        self.executions = []
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=None):
        self.executions.append((query, params))
        self.rowcount = 1


class _Connection:
    def __init__(self):
        self.test_cursor = _Cursor()
        self.commit_count = 0
        self.rollback_count = 0
        self.closed = False

    def cursor(self):
        return self.test_cursor

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1

    def close(self):
        self.closed = True


def _notices():
    return [
        {
            "title": "첫 공지",
            "author": "운영팀",
            "url": "https://public.example/notices",
            "detail_url": "https://public.example/notices/1",
            "external_id": "1",
            "published_at": "2026-08-25",
            "scraped_at": "2026-08-25T00:00:00+00:00",
            "content_type": "notice",
        },
        {
            "title": "두 공지",
            "author": "운영팀",
            "url": "https://public.example/notices",
            "detail_url": "https://public.example/notices/2",
            "external_id": "2",
            "published_at": "2026-08-24",
            "scraped_at": "2026-08-25T00:00:00+00:00",
            "content_type": "notice",
        },
    ]


def _persist_kwargs():
    return {
        "site_id": 42,
        "method_type": "GET",
        "api_url": "https://public.example/notices.json",
        "headers": {},
        "payload": {},
        "source_hash": "source-hash",
        "notices": _notices(),
        "processing_status": "success",
        "extractor_config": {"format": "agent_extractor_v1"},
        "schema_hash": "schema-hash",
        "extractor_confidence": 0.96,
    }


class AtomicRepositoryTests(unittest.TestCase):
    def test_scrape_timestamp_is_not_persisted_as_published_date(self):
        connection = _Connection()
        notices = [
            {
                "title": "게시일 없는 공고",
                "url": "https://public.example/notices",
                "detail_url": "https://public.example/notices/1",
                "external_id": "1",
                "published_at": None,
                "created_at": "2026-08-28T12:00:00+00:00",
                "scraped_at": "2026-08-28T12:00:00+00:00",
            }
        ]
        kwargs = _persist_kwargs()
        kwargs["notices"] = notices

        with (
            patch(
                "repositories.notice_repo.get_db_connection",
                return_value=connection,
            ),
            patch(
                "repositories.notice_repo._upsert_api_for_site_with_cursor",
                return_value=9,
            ),
            patch(
                "repositories.notice_repo._insert_or_update_notice_result_with_cursor",
                return_value=(101, True),
            ) as upsert_notice,
            patch(
                "repositories.notice_repo."
                "_activate_site_after_successful_sync_with_cursor"
            ),
        ):
            persist_verified_extraction(**kwargs)

        self.assertIsNone(upsert_notice.call_args.kwargs["published_at"])

    def test_verified_result_commits_all_writes_once(self):
        connection = _Connection()
        with (
            patch(
                "repositories.notice_repo.get_db_connection",
                return_value=connection,
            ),
            patch(
                "repositories.notice_repo._upsert_api_for_site_with_cursor",
                return_value=9,
            ) as upsert_api,
            patch(
                "repositories.notice_repo._insert_or_update_notice_result_with_cursor",
                side_effect=[(101, True), (102, True)],
            ) as upsert_notice,
            patch(
                "repositories.notice_repo."
                "_activate_site_after_successful_sync_with_cursor"
            ) as activate_site,
        ):
            result = persist_verified_extraction(**_persist_kwargs())

        self.assertEqual(result["api_id"], 9)
        self.assertEqual(result["persisted_notice_count"], 2)
        self.assertEqual(result["new_notice_ids"], [101, 102])
        self.assertEqual(result["new_notice_count"], 2)
        self.assertEqual(result["notification_event_ids"], [])
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        self.assertTrue(connection.closed)
        upsert_api.assert_called_once()
        self.assertEqual(upsert_notice.call_count, 2)
        activate_site.assert_called_once_with(connection.test_cursor, 42)
        executed_sql = "\n".join(
            query for query, _params in connection.test_cursor.executions
        )
        self.assertIn("UPDATE notices", executed_sql)
        self.assertIn("UPDATE api", executed_sql)

    def test_notice_failure_rolls_back_api_and_prior_notice(self):
        connection = _Connection()
        with (
            patch(
                "repositories.notice_repo.get_db_connection",
                return_value=connection,
            ),
            patch(
                "repositories.notice_repo._upsert_api_for_site_with_cursor",
                return_value=9,
            ),
            patch(
                "repositories.notice_repo._insert_or_update_notice_result_with_cursor",
                side_effect=[(101, True), RuntimeError("second notice failed")],
            ),
            patch(
                "repositories.notice_repo."
                "_activate_site_after_successful_sync_with_cursor"
            ) as activate_site,
        ):
            with self.assertRaisesRegex(RuntimeError, "second notice failed"):
                persist_verified_extraction(**_persist_kwargs())

        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 1)
        self.assertTrue(connection.closed)
        activate_site.assert_not_called()

    def test_valid_empty_activates_without_notice_writes(self):
        connection = _Connection()
        kwargs = _persist_kwargs()
        kwargs.update(notices=[], processing_status="valid_empty")
        with (
            patch(
                "repositories.notice_repo.get_db_connection",
                return_value=connection,
            ),
            patch(
                "repositories.notice_repo._upsert_api_for_site_with_cursor",
                return_value=9,
            ),
            patch(
                "repositories.notice_repo._insert_or_update_notice_result_with_cursor"
            ) as upsert_notice,
            patch(
                "repositories.notice_repo."
                "_activate_site_after_successful_sync_with_cursor"
            ) as activate_site,
        ):
            result = persist_verified_extraction(**kwargs)

        self.assertEqual(result["persisted_notice_count"], 0)
        upsert_notice.assert_not_called()
        activate_site.assert_called_once()
        self.assertEqual(connection.commit_count, 1)


class AtomicPipelineBoundaryTests(unittest.TestCase):
    def _api(self):
        return {
            "site_id": 42,
            "method_type": "GET",
            "api_url": "https://public.example/notices.json",
            "headers": {},
            "payload": {},
            "_pending_persistence": True,
            "extractor_config": {"format": "agent_extractor_v1"},
            "schema_hash": "schema-hash",
            "extractor_confidence": 0.96,
        }

    def test_success_uses_only_atomic_repository_boundary(self):
        api = self._api()
        with (
            patch(
                "dataController.scraper.scrape_auto.notice_repo."
                "persist_verified_extraction",
                return_value={"api_id": 9, "persisted_notice_count": 2},
            ) as persist,
            patch("dataController.scraper.scrape_auto.save_api") as legacy_save,
            patch(
                "dataController.scraper.scrape_auto.sync_notices_to_db"
            ) as legacy_sync,
            patch(
                "dataController.scraper.scrape_auto.notice_repo."
                "activate_site_after_successful_sync"
            ) as legacy_activate,
            patch(
                "dataController.scraper.scrape_auto.notice_repo.finish_crawl_run"
            ),
        ):
            status = _complete_structured_processing(
                api=api,
                target_url="https://public.example/notices",
                site_id=42,
                api_url="https://public.example/notices.json",
                new_hash="source-hash",
                structured={"status": "success", "notices": _notices()},
                crawl_run_id=11,
            )

        self.assertEqual(status, "success")
        self.assertFalse(api["_pending_persistence"])
        self.assertEqual(api["api_id"], 9)
        persist.assert_called_once()
        legacy_save.assert_not_called()
        legacy_sync.assert_not_called()
        legacy_activate.assert_not_called()

    def test_atomic_failure_keeps_registration_pending(self):
        api = self._api()
        with (
            patch(
                "dataController.scraper.scrape_auto.notice_repo."
                "persist_verified_extraction",
                side_effect=RuntimeError("transaction rolled back"),
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo."
                "update_api_processing_state"
            ) as update_api_state,
            patch(
                "dataController.scraper.scrape_auto.notice_repo."
                "update_site_crawl_state"
            ) as update_site_state,
            patch(
                "dataController.scraper.scrape_auto.notice_repo.finish_crawl_run"
            ) as finish_run,
        ):
            status = _complete_structured_processing(
                api=api,
                target_url="https://public.example/notices",
                site_id=42,
                api_url="https://public.example/notices.json",
                new_hash="source-hash",
                structured={"status": "success", "notices": _notices()},
                crawl_run_id=11,
            )

        self.assertEqual(status, "failed")
        self.assertTrue(api["_pending_persistence"])
        update_api_state.assert_not_called()
        update_site_state.assert_called_once()
        self.assertEqual(
            update_site_state.call_args.kwargs["validation_error_code"],
            "DATABASE_ERROR",
        )
        self.assertEqual(finish_run.call_args.kwargs["status"], "failed")


if __name__ == "__main__":
    unittest.main()
