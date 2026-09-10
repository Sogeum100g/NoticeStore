import datetime
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from dataController.scraper.notice_sync import sync_notices_to_db
from repositories.notice_repo import (
    build_notice_fallback_hash,
    insert_or_update_notice,
)


class NoticeIdentityRepositoryTests(unittest.TestCase):
    def _insert_with_new_identity(self, external_id: str, inserted_id: int):
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.__exit__.return_value = False
        # external_id 조회, detail_url 조회, INSERT RETURNING 순서입니다.
        cursor.fetchone.side_effect = [None, None, (inserted_id,)]
        connection = MagicMock()
        connection.cursor.return_value = cursor

        with patch(
            "repositories.notice_repo.get_db_connection",
            return_value=connection,
        ):
            result = insert_or_update_notice(
                site_id=12,
                title="R&D분야 외국인 경력사원 채용",
                author=f"회사 {external_id}",
                url="https://www.samsungcareers.com/hr/",
                created_at=None,
                scraped_at=datetime.datetime.now(datetime.timezone.utc),
                detail_url=(
                    "https://www.samsungcareers.com/hr/"
                    f"?no={external_id}"
                ),
                external_id=external_id,
                published_at="2026-08-20",
                record_hash=f"hash-{external_id}",
            )

        insert_queries = [
            query
            for query, _ in (
                call.args for call in cursor.execute.call_args_list
            )
            if "INSERT INTO notices" in query
        ]
        self.assertEqual(len(insert_queries), 1)
        self.assertNotIn("ON CONFLICT (site_id, title)", insert_queries[0])
        self.assertIn("ON CONFLICT DO NOTHING", insert_queries[0])
        return result

    def test_same_title_with_different_external_ids_inserts_distinct_rows(self):
        first_id = self._insert_with_new_identity("22922", 101)
        second_id = self._insert_with_new_identity("22844", 102)

        self.assertEqual(first_id, 101)
        self.assertEqual(second_id, 102)

    def test_fallback_identity_includes_author(self):
        common = {
            "title": "동일 제목 공고",
            "url": "https://public.example/notices",
            "published_at": "2026-08-20",
        }

        first = build_notice_fallback_hash(author="기관 A", **common)
        second = build_notice_fallback_hash(author="기관 B", **common)

        self.assertNotEqual(first, second)

    def test_migration_removes_title_constraint_and_adds_fallback_index(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20260824_use_notice_identity_keys.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("DROP CONSTRAINT IF EXISTS uq_notices_site_title", migration)
        self.assertIn("uq_notices_site_fallback_hash", migration)
        self.assertIn("external_id IS NULL", migration)
        self.assertIn("detail_url IS NULL", migration)


class NoticeSyncIdentityTests(unittest.TestCase):
    def test_sync_reports_every_distinct_persisted_record(self):
        notices = [
            {
                "title": "R&D분야 외국인 경력사원 채용",
                "author": "삼성디스플레이",
                "external_id": "22922",
                "detail_url": "https://www.samsungcareers.com/hr/?no=22922",
                "published_at": "2026-08-20",
                "url": "https://www.samsungcareers.com/hr/",
                "scraped_at": "2026-08-24T00:00:00+00:00",
            },
            {
                "title": "R&D분야 외국인 경력사원 채용",
                "author": "삼성SDI",
                "external_id": "22844",
                "detail_url": "https://www.samsungcareers.com/hr/?no=22844",
                "published_at": "2026-08-20",
                "url": "https://www.samsungcareers.com/hr/",
                "scraped_at": "2026-08-24T00:00:00+00:00",
            },
        ]

        with (
            patch(
                "dataController.scraper.notice_sync.notice_repo.get_db_connection",
            ) as get_connection,
            patch(
                "dataController.scraper.notice_sync.notice_repo."
                "_insert_or_update_notice_result_with_cursor",
                side_effect=[(101, True), (102, True)],
            ) as insert,
        ):
            connection = MagicMock()
            cursor = MagicMock()
            cursor.__enter__.return_value = cursor
            cursor.__exit__.return_value = False
            connection.cursor.return_value = cursor
            get_connection.return_value = connection
            persisted = sync_notices_to_db(
                12,
                notices,
                "source-hash",
                "https://www.samsungcareers.com/hr/list.data",
            )

        self.assertEqual(persisted["persisted_notice_count"], 2)
        self.assertEqual(persisted["new_notice_ids"], [101, 102])
        self.assertEqual(insert.call_count, 2)

    def test_sync_rejects_an_identity_collision(self):
        notices = [
            {
                "title": "동일 제목",
                "author": "기관 A",
                "external_id": "1",
                "detail_url": "https://public.example/1",
                "url": "https://public.example/",
                "scraped_at": "2026-08-24T00:00:00+00:00",
            },
            {
                "title": "동일 제목",
                "author": "기관 B",
                "external_id": "2",
                "detail_url": "https://public.example/2",
                "url": "https://public.example/",
                "scraped_at": "2026-08-24T00:00:00+00:00",
            },
        ]

        with (
            patch(
                "dataController.scraper.notice_sync.notice_repo.get_db_connection",
            ) as get_connection,
            patch(
                "dataController.scraper.notice_sync.notice_repo."
                "_insert_or_update_notice_result_with_cursor",
                side_effect=[(101, True), (101, False)],
            ),
        ):
            connection = MagicMock()
            cursor = MagicMock()
            cursor.__enter__.return_value = cursor
            cursor.__exit__.return_value = False
            connection.cursor.return_value = cursor
            get_connection.return_value = connection
            with self.assertRaisesRegex(
                RuntimeError,
                "동일한 DB 공지로 합쳐졌습니다",
            ):
                sync_notices_to_db(
                    12,
                    notices,
                    "source-hash",
                    "https://public.example/list",
                )


if __name__ == "__main__":
    unittest.main()
