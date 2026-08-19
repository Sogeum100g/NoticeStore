import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from dataController.scraper.page_extractors import get_text_hash
from dataController.scraper.processing_state import (
    classify_processing_result,
    decide_observation,
)
from dataController.scraper.scrape_auto import (
    _extraction_coverage_error,
    _refresh_html_extractor_decision,
    run_full_scrape,
)
from dataController.scraper.deterministic_extractor import ExtractionResult
from dataController.selector.candidate_analyzer import analyze_candidate_body
from dataController.selector.detect_api_auto import find_api, validate_candidate


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class StoredApiRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_stored_api_skips_collection_and_selector_llm(self):
        cached = {
            "site_id": 7,
            "api_url": "https://public.example/notices.json",
            "method_type": "GET",
        }
        with (
            patch(
                "dataController.selector.detect_api_auto.validate_public_url",
                return_value=SimpleNamespace(url="https://public.example/notices"),
            ),
            patch(
                "dataController.selector.detect_api_auto.notice_repo.select_api",
                return_value=cached,
            ),
            patch(
                "dataController.selector.detect_api_auto.notice_repo.update_site_crawl_state",
            ),
            patch(
                "dataController.selector.detect_api_auto.validate_candidate",
                new=AsyncMock(return_value=("passed", "fixture passed")),
            ),
            patch(
                "dataController.selector.detect_api_auto.collect_candidates",
                new=AsyncMock(),
            ) as collect,
            patch(
                "dataController.selector.detect_api_auto.prioritize_candidates",
                new=AsyncMock(),
            ) as prioritize,
        ):
            result = await find_api("https://public.example/notices")

        self.assertEqual(result["api_url"], cached["api_url"])
        self.assertFalse(result["_pending_persistence"])
        collect.assert_not_awaited()
        prioritize.assert_not_awaited()

    async def test_invalid_stored_api_falls_back_to_candidate_discovery(self):
        cached = {
            "site_id": 7,
            "api_url": "https://public.example/stale.json",
            "method_type": "GET",
        }
        replacement = {
            "api_index": 2,
            "api_url": "https://public.example/notices.json",
            "method_type": "GET",
        }
        with (
            patch(
                "dataController.selector.detect_api_auto.validate_public_url",
                return_value=SimpleNamespace(url="https://public.example/notices"),
            ),
            patch(
                "dataController.selector.detect_api_auto.notice_repo.select_api",
                return_value=cached,
            ),
            patch(
                "dataController.selector.detect_api_auto.notice_repo.select_site_id",
                return_value=7,
            ),
            patch(
                "dataController.selector.detect_api_auto.notice_repo.update_site_crawl_state",
            ),
            patch(
                "dataController.selector.detect_api_auto.validate_candidate",
                new=AsyncMock(
                    side_effect=[
                        ("semantic_failed", "stale"),
                        ("passed", "replacement passed"),
                    ]
                ),
            ),
            patch(
                "dataController.selector.detect_api_auto.collect_candidates",
                new=AsyncMock(return_value=[replacement]),
            ) as collect,
            patch(
                "dataController.selector.detect_api_auto.prioritize_candidates",
                new=AsyncMock(return_value=[replacement]),
            ) as prioritize,
        ):
            result = await find_api("https://public.example/notices")

        collect.assert_awaited_once()
        prioritize.assert_awaited_once()
        self.assertEqual(result["api_url"], replacement["api_url"])
        self.assertTrue(result["_pending_persistence"])


class ProcessingStateRegressionTests(unittest.TestCase):
    def test_successful_empty_result_is_valid_empty(self):
        status, error = classify_processing_result(
            {"status": "success", "notices": []}
        )
        self.assertEqual(status, "valid_empty")
        self.assertIsNone(error)

    def test_same_failed_hash_respects_backoff(self):
        decision = decide_observation(
            "same-hash",
            {
                "last_observed_hash": "same-hash",
                "processing_status": "failed",
                "retry_count": 1,
                "next_retry_at": "2099-01-01T00:00:00+00:00",
            },
        )
        self.assertEqual(decision, "backoff")

    def test_same_failed_hash_stops_after_retry_cap(self):
        decision = decide_observation(
            "same-hash",
            {
                "last_observed_hash": "same-hash",
                "processing_status": "failed",
                "retry_count": 3,
            },
        )
        self.assertEqual(decision, "retry_exhausted")

    def test_old_html_extractor_rule_reprocesses_unchanged_source(self):
        decision = _refresh_html_extractor_decision(
            "unchanged",
            {
                "extractor_config": {
                    "version": 2,
                    "source_type": "html",
                    "record_css": "ul.card_list > li",
                }
            },
        )
        self.assertEqual(decision, "process")

    def test_current_html_extractor_rule_keeps_unchanged_decision(self):
        decision = _refresh_html_extractor_decision(
            "unchanged",
            {
                "extractor_config": {
                    "version": 4,
                    "source_type": "html",
                    "record_css": "ul.card_list > li",
                }
            },
        )
        self.assertEqual(decision, "unchanged")

    def test_large_semantic_to_extraction_drop_is_rejected(self):
        error = _extraction_coverage_error(
            {
                "validation_analysis": {
                    "semantic_record_count": 9,
                }
            },
            ExtractionResult(
                status="success",
                notices=[{"title": "첫 공고"}],
                extractor_config=None,
                schema_hash=None,
                confidence=0.82,
                intermediate=None,
            ),
        )
        self.assertIn("semantic_records=9", error)
        self.assertIn("extracted_records=1", error)

    def test_matching_semantic_and_extraction_counts_are_accepted(self):
        error = _extraction_coverage_error(
            {
                "validation_analysis": {
                    "semantic_record_count": 14,
                }
            },
            ExtractionResult(
                status="success",
                notices=[
                    {"title": f"공지 {index}"}
                    for index in range(14)
                ],
                extractor_config=None,
                schema_hash=None,
                confidence=0.96,
                intermediate=None,
            ),
        )
        self.assertIsNone(error)


class RawHashCacheRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_processed_json_hash_skips_extraction(self):
        raw_data = json.loads(
            (FIXTURE_DIR / "notices.json").read_text(encoding="utf-8")
        )
        canonical = json.dumps(
            raw_data,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        processed_hash = get_text_hash(canonical)

        response = Mock()
        response.headers = {"Content-Type": "application/json"}
        response.apparent_encoding = "utf-8"
        response.encoding = "utf-8"
        response.raise_for_status.return_value = None
        response.json.return_value = raw_data

        api = {
            "site_id": 7,
            "api_id": 9,
            "api_url": "https://public.example/notices.json",
            "method_type": "GET",
            "headers": {},
            "payload": {},
            "_pending_persistence": False,
        }

        with (
            patch(
                "dataController.scraper.scrape_auto.expand_url",
                return_value="https://public.example/notices",
            ),
            patch(
                "dataController.scraper.scrape_auto.is_crawling_allowed",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "dataController.scraper.scrape_auto.find_api",
                new=AsyncMock(return_value=api),
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo.select_processing_state",
                return_value={"last_processed_hash": processed_hash},
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo.get_latest_notice_title",
                return_value="기존 공지",
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo.create_crawl_run",
                return_value=11,
            ) as create_run,
            patch(
                "dataController.scraper.scrape_auto.notice_repo.finish_crawl_run",
            ),
            patch(
                "dataController.scraper.scrape_auto.safe_request",
                return_value=response,
            ),
            patch(
                "dataController.scraper.scrape_auto.get_recent_info",
                return_value={"notices": [{"title": "기존 공지"}]},
            ),
        ):
            result = await run_full_scrape("https://public.example/notices")

        self.assertEqual(result["status"], "unchanged")
        create_kwargs = create_run.call_args.kwargs
        self.assertEqual(create_kwargs["selection_decision"], "cached_reuse")
        self.assertIsNone(create_kwargs["candidate_evidence"])

    def test_structuring_error_is_failed_not_valid_empty(self):
        status, error = classify_processing_result(
            {"status": "error", "notices": [], "error_msg": "model timeout"}
        )
        self.assertEqual(status, "failed")
        self.assertEqual(error, "model timeout")

    def test_nonempty_result_is_success(self):
        status, error = classify_processing_result(
            {"status": "success", "notices": [{"title": "공지"}]}
        )
        self.assertEqual(status, "success")
        self.assertIsNone(error)


class StoredFixtureRegressionTests(unittest.TestCase):
    def _analyze(self, filename, *, body_shape, content_type):
        body = (FIXTURE_DIR / filename).read_text(encoding="utf-8")
        return analyze_candidate_body(
            body,
            body_shape=body_shape,
            content_type=content_type,
        )

    def test_json_fixture(self):
        analysis = self._analyze(
            "notices.json",
            body_shape="json_object",
            content_type="application/json",
        )
        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 2)

    def test_jsonp_fixture(self):
        analysis = self._analyze(
            "notices.jsonp",
            body_shape="jsonp_wrapper",
            content_type="application/javascript",
        )
        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 2)

    def test_html_fixture(self):
        analysis = self._analyze(
            "notices.html",
            body_shape="html",
            content_type="text/html",
        )
        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 2)

    def test_split_cell_list_rows_are_semantic_records(self):
        html = """
        <div class="tb-body">
          <ul>
            <li><a href="#a">첫 번째 학사 공지 안내</a></li>
            <li>컴퓨터과학부</li>
            <li>2026-07-23</li>
          </ul>
          <ul>
            <li><a href="#a">두 번째 학사 공지 안내</a></li>
            <li>컴퓨터과학부</li>
            <li>2026-07-15</li>
          </ul>
        </div>
        """
        analysis = analyze_candidate_body(
            html,
            body_shape="html",
            content_type="text/html",
        )
        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 2)

    def test_camel_case_structured_roles_are_semantic_records(self):
        analysis = analyze_candidate_body(
            json.dumps(
                {
                    "jobList": [
                        {
                            "realId": "P-100",
                            "jobOfferTitle": "AI Platform Engineer",
                            "regDate": "2026-07-20T10:00:00",
                        },
                        {
                            "realId": "P-101",
                            "jobOfferTitle": "Data Platform Engineer",
                            "regDate": "2026-07-19T10:00:00",
                        },
                    ]
                }
            ),
            body_shape="json_object",
            content_type="application/json",
        )
        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 2)
        self.assertEqual(
            analysis["data_key_hits"],
            ["date", "list", "title"],
        )


class PostCandidateRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_fixture_preserves_json_payload_for_replay(self):
        body = (FIXTURE_DIR / "notices.json").read_text(encoding="utf-8")
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "application/json"}
        response.content = body.encode("utf-8")
        response.text = body
        response.encoding = "utf-8"
        response.apparent_encoding = "utf-8"

        candidate = {
            "api_url": "https://public.example/search",
            "method_type": "POST",
            "source_kind": "xhr_json",
            "headers": {"content-type": "application/json", "Cookie": "secret"},
            "payload": {"page": 1, "category": "notice"},
            "body_payload": {"page": 1, "category": "notice"},
            "payload_format": "json",
        }

        with (
            patch(
                "dataController.selector.detect_api_auto.safe_request",
                return_value=response,
            ) as request,
            patch(
                "dataController.selector.detect_api_auto.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda func, *args: func(*args)),
            ),
        ):
            status, _ = await validate_candidate(candidate)

        self.assertEqual(status, "passed")
        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs["json"], {"page": 1, "category": "notice"})
        self.assertNotIn("Cookie", kwargs["headers"])


if __name__ == "__main__":
    unittest.main()
