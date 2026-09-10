import unittest
from unittest.mock import AsyncMock, Mock, patch

import requests

from dataController.scraper.scrape_auto import run_full_scrape


class CandidateExtractionFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_access_denial_sets_site_access_blocked(self):
        blocked_response = Mock()
        blocked_response.status_code = 430
        blocked_response.url = "https://public.example/notices"
        blocked_response.apparent_encoding = "utf-8"
        blocked_response.raise_for_status.side_effect = requests.HTTPError(
            "430 access denied",
            response=blocked_response,
        )
        selected = {
            "site_id": 7,
            "api_index": 1,
            "api_url": "https://public.example/notices",
            "method_type": "GET",
            "headers": {},
            "payload": {},
            "selection_mode": "cached",
            "_pending_persistence": False,
        }

        with (
            patch(
                "dataController.scraper.scrape_auto.expand_url",
                return_value="https://public.example/notices",
            ),
            patch(
                "dataController.scraper.scrape_auto.find_api",
                new=AsyncMock(return_value=selected),
            ),
            patch(
                "dataController.scraper.scrape_auto.safe_request",
                return_value=blocked_response,
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo."
                "select_processing_state",
                return_value=None,
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo.create_crawl_run",
                return_value=23,
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo.finish_crawl_run",
            ) as finish_run,
            patch(
                "dataController.scraper.scrape_auto.notice_repo."
                "update_site_crawl_state",
            ) as update_state,
        ):
            result = await run_full_scrape(
                "https://public.example/notices",
                site_id=7,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["site_id"], 7)
        finish_run.assert_called_once_with(
            23,
            status="blocked",
            error_code="SITE_ACCESS_BLOCKED",
            error_message="원격 사이트가 HTTP 430로 접근을 거부했습니다.",
        )
        update_state.assert_called_once_with(
            7,
            crawl_status="blocked",
            validation_status="valid",
            validation_error_code="SITE_ACCESS_BLOCKED",
            validation_error="원격 사이트가 HTTP 430로 접근을 거부했습니다.",
        )

    async def test_validated_snapshot_is_consumed_without_refetch(self):
        selected = {
            "site_id": 7,
            "api_index": 1,
            "api_url": "https://public.example/notices.json",
            "method_type": "GET",
            "headers": {},
            "payload": {},
            "selection_mode": "rule_based",
            "_pending_persistence": True,
            "_validated_response_snapshot": {
                "body_text": (
                    '{"items":[{"title":"검증된 공지",'
                    '"date":"2026-08-28"}]}'
                ),
                "content_type": "application/json",
                "response_url": "https://public.example/notices.json",
                "decoded_bytes": 70,
            },
        }

        with (
            patch(
                "dataController.scraper.scrape_auto.expand_url",
                return_value="https://public.example/notices",
            ),
            patch(
                "dataController.scraper.scrape_auto.find_api",
                new=AsyncMock(return_value=selected),
            ),
            patch(
                "dataController.scraper.scrape_auto.safe_request",
            ) as safe_request,
            patch(
                "dataController.scraper.scrape_auto.notice_repo."
                "select_processing_state",
                return_value=None,
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo.create_crawl_run",
                return_value=21,
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo.finish_crawl_run",
            ),
            patch(
                "dataController.scraper.scrape_auto.decide_observation",
                return_value="unchanged",
            ),
            patch(
                "dataController.scraper.scrape_auto."
                "_refresh_notice_identity_decision",
                return_value="unchanged",
            ),
            patch(
                "dataController.scraper.scrape_auto.get_recent_info",
                return_value={"notices": [{"title": "기존 공지"}]},
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo."
                "activate_site_after_successful_sync",
            ),
        ):
            result = await run_full_scrape(
                "https://public.example/notices",
                site_id=7,
            )

        self.assertEqual(result["status"], "unchanged")
        safe_request.assert_not_called()

    async def test_http_failure_retries_next_validated_candidate(self):
        second_response = Mock()
        second_response.headers = {"Content-Type": "application/json"}
        second_response.apparent_encoding = "utf-8"
        second_response.encoding = "utf-8"
        second_response.url = "https://public.example/notices.json"
        second_response.raise_for_status.return_value = None
        second_response.text = (
            '{"items":[{"title":"새 공지","date":"2026-08-28"}]}'
        )

        fallback = {
            "site_id": 7,
            "api_index": 2,
            "api_url": "https://public.example/notices.json",
            "method_type": "GET",
            "headers": {},
            "payload": {},
            "selection_mode": "extraction_fallback",
            "_pending_persistence": True,
        }
        selected = {
            "site_id": 7,
            "api_index": 1,
            "api_url": "https://public.example/menu-manifest.json",
            "method_type": "GET",
            "headers": {},
            "payload": {},
            "selection_mode": "rule_based",
            "_pending_persistence": True,
            "_fallback_candidates": [fallback],
        }

        with (
            patch(
                "dataController.scraper.scrape_auto.expand_url",
                return_value="https://public.example/notices",
            ) as expand_url,
            patch(
                "dataController.scraper.scrape_auto.find_api",
                new=AsyncMock(return_value=selected),
            ) as find_api,
            patch(
                "dataController.scraper.scrape_auto.safe_request",
                side_effect=[
                    requests.exceptions.ConnectionError("manifest unavailable"),
                    second_response,
                ],
            ) as safe_request,
            patch(
                "dataController.scraper.scrape_auto.notice_repo."
                "select_processing_state",
                return_value=None,
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo.create_crawl_run",
                side_effect=[11, 12],
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo.finish_crawl_run",
            ) as finish_run,
            patch(
                "dataController.scraper.scrape_auto.decide_observation",
                return_value="unchanged",
            ),
            patch(
                "dataController.scraper.scrape_auto."
                "_refresh_notice_identity_decision",
                return_value="unchanged",
            ),
            patch(
                "dataController.scraper.scrape_auto.get_recent_info",
                return_value={"notices": [{"title": "기존 공지"}]},
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo."
                "activate_site_after_successful_sync",
            ),
        ):
            result = await run_full_scrape(
                "https://public.example/notices",
                site_id=7,
            )

        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(safe_request.call_count, 2)
        find_api.assert_awaited_once()
        expand_url.assert_called_once()
        first_finish = finish_run.call_args_list[0]
        self.assertEqual(first_finish.args[0], 11)
        self.assertEqual(
            first_finish.kwargs["error_code"],
            "CANDIDATE_HTTP_REQUEST_FAILED",
        )


if __name__ == "__main__":
    unittest.main()
