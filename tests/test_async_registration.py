import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from schemas import SiteRequest
from routers.subscription_router import add_new_site


class AsyncSiteRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_site_returns_pending_without_waiting_for_scrape(self):
        request = SiteRequest(
            url="https://public.example/notices#latest",
            alias="학교 공지",
        )

        with (
            patch(
                "routers.subscription_router.get_user_max_sites_limit",
                return_value=5,
            ),
            patch(
                "routers.subscription_router.get_current_subscription_count",
                return_value=1,
            ),
            patch(
                "routers.subscription_router.asyncio.to_thread",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        url="https://public.example/notices"
                    )
                ),
            ),
            patch(
                "routers.subscription_router.select_site_id",
                return_value=None,
            ),
            patch(
                "routers.subscription_router.insert_site",
                return_value=42,
            ) as insert_site,
            patch("routers.subscription_router.record_site_submission"),
            patch(
                "routers.subscription_router.add_user_subscription",
                return_value=True,
            ) as subscribe,
            patch(
                "routers.subscription_router.scrape_target_site.delay",
            ) as enqueue,
            patch(
                "routers.subscription_router.get_user_site_status",
                return_value={
                    "crawl_status": "pending",
                    "registration_completed": False,
                },
            ),
        ):
            result = await add_new_site(request=request, user_id=9)

        self.assertEqual(
            result,
            {
                "status": "success",
                "message": "PENDING",
                "site_id": 42,
                "crawl_status": "pending",
                "registration_completed": False,
            },
        )
        insert_site.assert_called_once()
        subscribe.assert_called_once_with(9, 42, "학교 공지")
        enqueue.assert_called_once_with(
            42,
            "https://public.example/notices",
        )

    async def test_add_existing_active_site_returns_completed_state(self):
        request = SiteRequest(
            url="https://public.example/notices",
            alias="학교 공지",
        )

        with (
            patch(
                "routers.subscription_router.get_user_max_sites_limit",
                return_value=5,
            ),
            patch(
                "routers.subscription_router.get_current_subscription_count",
                return_value=1,
            ),
            patch(
                "routers.subscription_router.asyncio.to_thread",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        url="https://public.example/notices"
                    )
                ),
            ),
            patch(
                "routers.subscription_router.select_site_id",
                return_value=42,
            ),
            patch("routers.subscription_router.record_site_submission"),
            patch(
                "routers.subscription_router.add_user_subscription",
                return_value=True,
            ),
            patch("routers.subscription_router.scrape_target_site.delay"),
            patch(
                "routers.subscription_router.get_user_site_status",
                return_value={
                    "crawl_status": "active",
                    "registration_completed": True,
                },
            ),
        ):
            result = await add_new_site(request=request, user_id=9)

        self.assertEqual(result["message"], "ACTIVE")
        self.assertEqual(result["crawl_status"], "active")
        self.assertTrue(result["registration_completed"])

    async def test_pending_site_queue_failure_is_exposed_as_failed_state(self):
        request = SiteRequest(
            url="https://public.example/notices",
            alias="학교 공지",
        )

        with (
            patch(
                "routers.subscription_router.get_user_max_sites_limit",
                return_value=5,
            ),
            patch(
                "routers.subscription_router.get_current_subscription_count",
                return_value=1,
            ),
            patch(
                "routers.subscription_router.asyncio.to_thread",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        url="https://public.example/notices"
                    )
                ),
            ),
            patch(
                "routers.subscription_router.select_site_id",
                return_value=42,
            ),
            patch("routers.subscription_router.record_site_submission"),
            patch(
                "routers.subscription_router.add_user_subscription",
                return_value=True,
            ),
            patch(
                "routers.subscription_router.get_user_site_status",
                return_value={
                    "crawl_status": "pending",
                    "registration_completed": False,
                },
            ),
            patch(
                "routers.subscription_router.scrape_target_site.delay",
                side_effect=RuntimeError("redis unavailable"),
            ),
            patch(
                "routers.subscription_router.update_site_crawl_state",
            ) as update_state,
        ):
            with self.assertRaises(HTTPException) as raised:
                await add_new_site(request=request, user_id=9)

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "CRAWL_QUEUE_UNAVAILABLE")
        update_state.assert_called_once_with(
            42,
            crawl_status="failed",
            validation_error_code="CRAWL_QUEUE_UNAVAILABLE",
            validation_error="크롤링 작업을 대기열에 등록하지 못했습니다.",
        )

    async def test_active_site_stays_registered_when_refresh_queue_is_down(self):
        request = SiteRequest(
            url="https://public.example/notices",
            alias="학교 공지",
        )

        with (
            patch(
                "routers.subscription_router.get_user_max_sites_limit",
                return_value=5,
            ),
            patch(
                "routers.subscription_router.get_current_subscription_count",
                return_value=1,
            ),
            patch(
                "routers.subscription_router.asyncio.to_thread",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        url="https://public.example/notices"
                    )
                ),
            ),
            patch(
                "routers.subscription_router.select_site_id",
                return_value=42,
            ),
            patch("routers.subscription_router.record_site_submission"),
            patch(
                "routers.subscription_router.add_user_subscription",
                return_value=True,
            ),
            patch(
                "routers.subscription_router.get_user_site_status",
                return_value={
                    "crawl_status": "active",
                    "registration_completed": True,
                },
            ),
            patch(
                "routers.subscription_router.scrape_target_site.delay",
                side_effect=RuntimeError("redis unavailable"),
            ),
            patch(
                "routers.subscription_router.update_site_crawl_state",
            ) as update_state,
        ):
            result = await add_new_site(request=request, user_id=9)

        self.assertEqual(result["message"], "ACTIVE")
        update_state.assert_not_called()


if __name__ == "__main__":
    unittest.main()
