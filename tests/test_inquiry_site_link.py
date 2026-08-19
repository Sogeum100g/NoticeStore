import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException

from routers.inquiry_router import submit_inquiry
from schemas import InquiryRequest


class InquirySiteLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_general_inquiry_remains_backward_compatible(self):
        request = InquiryRequest(
            category="기타",
            title="일반 문의",
            content="사이트와 무관한 문의입니다.",
        )
        background_tasks = BackgroundTasks()

        with (
            patch(
                "routers.inquiry_router.get_user_info_by_id",
                return_value={
                    "email": "user@example.com",
                    "nickname": "tester",
                },
            ),
            patch(
                "routers.inquiry_router.insert_inquiry",
                return_value=True,
            ) as insert,
            patch(
                "routers.inquiry_router.get_user_inquiry_site_context",
            ) as get_context,
        ):
            result = await submit_inquiry(
                request=request,
                background_tasks=background_tasks,
                user_id=9,
            )

        get_context.assert_not_called()
        insert.assert_called_once_with(
            9,
            "기타",
            "일반 문의",
            "사이트와 무관한 문의입니다.",
            site_id=None,
            crawl_run_id=None,
        )
        self.assertEqual(result["status"], "success")
        self.assertIsNone(result["site_id"])

    async def test_subscribed_site_and_latest_run_are_linked(self):
        request = InquiryRequest(
            category="버그 제보",
            title="공지 추출 실패",
            content="이 사이트의 공지가 보이지 않습니다.",
            site_id=42,
        )
        background_tasks = BackgroundTasks()
        context = {
            "site_id": 42,
            "crawl_status": "failed",
            "crawl_run_id": 81,
            "crawl_run_status": "failed",
            "error_code": "PROCESSING_FAILED",
        }

        with (
            patch(
                "routers.inquiry_router.get_user_info_by_id",
                return_value={
                    "email": "user@example.com",
                    "nickname": "tester",
                },
            ),
            patch(
                "routers.inquiry_router.get_user_inquiry_site_context",
                return_value=context,
            ) as get_context,
            patch(
                "routers.inquiry_router.insert_inquiry",
                return_value=True,
            ) as insert,
        ):
            result = await submit_inquiry(
                request=request,
                background_tasks=background_tasks,
                user_id=9,
            )

        get_context.assert_called_once_with(9, 42)
        insert.assert_called_once_with(
            9,
            "버그 제보",
            "공지 추출 실패",
            "이 사이트의 공지가 보이지 않습니다.",
            site_id=42,
            crawl_run_id=81,
        )
        self.assertEqual(result["crawl_run_id"], 81)
        self.assertEqual(len(background_tasks.tasks), 1)
        self.assertEqual(background_tasks.tasks[0].args[-1], context)

    async def test_other_users_site_cannot_be_linked(self):
        request = InquiryRequest(
            category="버그 제보",
            title="권한 없는 사이트",
            content="문의",
            site_id=42,
        )

        with (
            patch(
                "routers.inquiry_router.get_user_info_by_id",
                return_value={"email": "user@example.com"},
            ),
            patch(
                "routers.inquiry_router.get_user_inquiry_site_context",
                return_value=None,
            ),
            patch(
                "routers.inquiry_router.insert_inquiry",
            ) as insert,
        ):
            with self.assertRaises(HTTPException) as raised:
                await submit_inquiry(
                    request=request,
                    background_tasks=BackgroundTasks(),
                    user_id=9,
                )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(
            raised.exception.detail,
            "SUBSCRIBED_SITE_NOT_FOUND",
        )
        insert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
