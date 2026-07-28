import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
        ):
            result = await add_new_site(request=request, user_id=9)

        self.assertEqual(
            result,
            {"status": "success", "message": "PENDING", "site_id": 42},
        )
        insert_site.assert_called_once()
        subscribe.assert_called_once_with(9, 42, "학교 공지")
        enqueue.assert_called_once_with(
            42,
            "https://public.example/notices",
        )


if __name__ == "__main__":
    unittest.main()
