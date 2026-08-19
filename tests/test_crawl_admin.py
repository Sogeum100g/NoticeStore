import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from routers.crawl_admin_router import (
    read_crawl_review_queue,
    update_crawl_run_review,
)
from schemas import CrawlRunReviewRequest


class CrawlRunReviewSchemaTests(unittest.TestCase):
    def test_unknown_review_label_is_rejected(self):
        with self.assertRaises(ValidationError):
            CrawlRunReviewRequest(label="maybe")


class CrawlAdminRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_review_queue_passes_bounded_filters(self):
        rows = [{"crawl_run_id": 3, "review_label": None}]
        with patch(
            "routers.crawl_admin_router.get_crawl_runs_for_review",
            return_value=rows,
        ) as get_queue:
            result = await read_crawl_review_queue(
                reviewed=False,
                run_status="failed",
                limit=20,
                admin_id=9,
            )

        get_queue.assert_called_once_with(
            reviewed=False,
            status="failed",
            limit=20,
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["data"], rows)

    async def test_admin_can_label_a_crawl_run(self):
        request = CrawlRunReviewRequest(
            label="incorrect",
            review_notes="API가 공지 목록이 아닌 검색 추천 결과입니다.",
        )
        with patch(
            "routers.crawl_admin_router.review_crawl_run",
            return_value=True,
        ) as review:
            result = await update_crawl_run_review(
                crawl_run_id=17,
                request=request,
                admin_id=9,
            )

        review.assert_called_once_with(
            17,
            reviewer_id=9,
            label="incorrect",
            review_notes="API가 공지 목록이 아닌 검색 추천 결과입니다.",
        )
        self.assertEqual(result["review_label"], "incorrect")

    async def test_missing_crawl_run_returns_404(self):
        request = CrawlRunReviewRequest(label="correct")
        with patch(
            "routers.crawl_admin_router.review_crawl_run",
            return_value=False,
        ):
            with self.assertRaises(HTTPException) as raised:
                await update_crawl_run_review(
                    crawl_run_id=999,
                    request=request,
                    admin_id=9,
                )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "CRAWL_RUN_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
