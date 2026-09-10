import unittest
from datetime import datetime
from unittest.mock import patch

from repositories.folder_repo import get_favorite_folders_tree


class _FakeCursor:
    def __init__(self):
        self._result_index = 0
        self._results = [
            [
                {
                    "folder_id": 3,
                    "parent_folder_id": None,
                    "folder_name": "채용",
                    "sort_order": 0,
                }
            ],
            [
                {
                    "folder_id": 3,
                    "notice_id": 17,
                    "title": "신입 채용",
                    "author": "인사팀",
                    "url": "https://example.com/17",
                    "site_id": 9,
                    "published_at": datetime(2026, 8, 20, 0, 0),
                    "created_at": datetime(2026, 8, 25, 9, 30),
                }
            ],
            [],
        ]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params):
        if "FROM favorite_notices" in query:
            assert "n.author" in query
            assert "n.published_at" in query

    def fetchall(self):
        result = self._results[self._result_index]
        self._result_index += 1
        return result


class _FakeConnection:
    def __init__(self):
        self.cursor_instance = _FakeCursor()
        self.closed = False

    def cursor(self, **kwargs):
        return self.cursor_instance

    def close(self):
        self.closed = True


class FavoriteFolderTreeTests(unittest.TestCase):
    def test_notice_author_and_date_are_included_in_tree(self):
        connection = _FakeConnection()

        with patch(
            "repositories.folder_repo.get_db_connection",
            return_value=connection,
        ):
            tree = get_favorite_folders_tree(user_id=5)

        notice = tree[0]["notices"][0]
        self.assertEqual(notice["author"], "인사팀")
        self.assertEqual(notice["published_at"], "2026-08-20T00:00:00")
        self.assertEqual(notice["created_at"], "2026-08-25T09:30:00")
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
