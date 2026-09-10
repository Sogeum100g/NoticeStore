import unittest
from unittest.mock import patch

from fastapi import HTTPException

from routers.subscription_router import (
    read_favorite_sites,
    read_site_status,
    remove_subscription,
)
from services.site_error_service import (
    SITE_ERROR_MESSAGES,
    get_public_site_error_code,
    get_site_error_message,
)


class SiteErrorMessageTests(unittest.TestCase):
    def test_every_registration_failure_code_has_a_distinct_user_message(self):
        expected_codes = {
            "CRAWL_QUEUE_UNAVAILABLE",
            "ROBOTS_TXT_BLOCKED",
            "SITE_VALIDATION_FAILED",
            "SITE_ACCESS_BLOCKED",
            "SITE_UNREACHABLE",
            "DATABASE_ERROR",
            "SITE_REGISTRATION_FAILED",
        }

        self.assertEqual(set(SITE_ERROR_MESSAGES), expected_codes)
        self.assertEqual(
            len(set(SITE_ERROR_MESSAGES.values())),
            len(SITE_ERROR_MESSAGES),
        )

    def test_internal_extraction_codes_share_one_public_result(self):
        for internal_code in (
            "NO_NOTICE_SOURCE",
            "SITE_VALIDATION_FAILED",
            "NOTICE_EXTRACTION_FAILED",
        ):
            self.assertEqual(
                get_public_site_error_code(internal_code),
                "SITE_VALIDATION_FAILED",
            )
            self.assertEqual(
                get_site_error_message(internal_code),
                SITE_ERROR_MESSAGES["SITE_VALIDATION_FAILED"],
            )

    def test_unknown_code_uses_safe_generic_message(self):
        self.assertEqual(
            get_site_error_message("UNEXPECTED_INTERNAL_ERROR"),
            SITE_ERROR_MESSAGES["SITE_REGISTRATION_FAILED"],
        )


class SiteErrorResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_subscription_keeps_404_status(self):
        with patch(
            "routers.subscription_router.delete_user_subscription",
            return_value=False,
        ):
            with self.assertRaises(HTTPException) as raised:
                await remove_subscription(site_id=42, user_id=9)

        self.assertEqual(raised.exception.status_code, 404)

    async def test_subscription_list_exposes_code_and_safe_message(self):
        row = (
            42,
            "https://public.example/notices",
            "학교 공지",
            False,
            "failed",
            "NO_NOTICE_SOURCE",
            "수집된 API 후보가 없습니다.",
            False,
            False,
        )
        with patch(
            "routers.subscription_router.get_user_specific_sites",
            return_value=[row],
        ):
            result = await read_favorite_sites(user_id=9)

        site = result["sites"][0]
        self.assertEqual(site["error_code"], "SITE_VALIDATION_FAILED")
        self.assertEqual(
            site["error_message"],
            SITE_ERROR_MESSAGES["SITE_VALIDATION_FAILED"],
        )
        self.assertEqual(site["validation_error"], row[6])
        self.assertFalse(site["notification_enabled"])

    async def test_status_endpoint_exposes_code_and_safe_message(self):
        with patch(
            "routers.subscription_router.get_user_site_status",
            return_value={
                "site_id": 42,
                "crawl_status": "blocked",
                "validation_error_code": "ROBOTS_TXT_BLOCKED",
                "validation_error": "robots.txt가 크롤링을 허용하지 않습니다.",
                "registration_completed": False,
            },
        ):
            result = await read_site_status(site_id=42, user_id=9)

        site = result["site"]
        self.assertNotIn("validation_error_code", site)
        self.assertEqual(site["error_code"], "ROBOTS_TXT_BLOCKED")
        self.assertEqual(
            site["error_message"],
            SITE_ERROR_MESSAGES["ROBOTS_TXT_BLOCKED"],
        )


if __name__ == "__main__":
    unittest.main()
