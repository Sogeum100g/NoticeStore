import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from dataController.scraper.page_extractors import (
    extract_yt_data,
    get_text_hash,
    parse_youtube_community_data,
)
from dataController.scraper.processing_state import (
    classify_processing_result,
    decide_observation,
)
from dataController.scraper.scrape_auto import (
    _apply_deterministic_result,
    _complete_notice_identity_upgrade,
    _extraction_coverage_diagnostics,
    _refresh_detail_url_base_decision,
    _refresh_html_extractor_decision,
    _refresh_notice_identity_decision,
    _update_site_after_skipped_observation,
    run_full_scrape,
)
from dataController.scraper.active_rule_config import DETAIL_URL_BASE_VERSION
from dataController.scraper.deterministic_extractor import ExtractionResult
from dataController.selector.candidate_analyzer import analyze_candidate_body
from dataController.selector.detect_api_auto import (
    _sync_validate_candidate,
    find_api,
    validate_candidate,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _youtube_posts_html(assignment: str = "var ytInitialData =") -> str:
    data = {
        "contents": [
            {
                "backstagePostRenderer": {
                    "postId": f"post-{index}",
                    "contentText": {"runs": [{"text": f"커뮤니티 게시물 {index}"}]},
                    "publishedTimeText": {"runs": [{"text": f"{index}일 전"}]},
                }
            }
            for index in range(1, 3)
        ]
    }
    return (
        "<html><head><script>"
        f"{assignment}{json.dumps(data, ensure_ascii=False)};"
        "</script></head><body><h1>채널</h1></body></html>"
    )


class StoredApiRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_redirected_cache_is_loaded_by_registration_site_id(self):
        cached = {
            "site_id": 42,
            "api_url": "https://final.example/notices.json",
            "method_type": "GET",
        }
        with (
            patch(
                "dataController.selector.detect_api_auto.validate_public_url",
                return_value=SimpleNamespace(url="https://final.example/notices"),
            ),
            patch(
                "dataController.selector.detect_api_auto.notice_repo."
                "select_api_by_site_id",
                return_value=cached,
            ) as select_by_site_id,
            patch(
                "dataController.selector.detect_api_auto.notice_repo.select_api",
            ) as select_by_url,
            patch(
                "dataController.selector.detect_api_auto.notice_repo.update_site_crawl_state",
            ) as update_state,
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
            result = await find_api(
                "https://final.example/notices",
                site_id=42,
            )

        self.assertEqual(result["site_id"], 42)
        self.assertFalse(result["_pending_persistence"])
        select_by_site_id.assert_called_once_with(42)
        select_by_url.assert_not_called()
        collect.assert_not_awaited()
        prioritize.assert_not_awaited()
        update_state.assert_called_once_with(
            42,
            crawl_status="active",
            validation_status="valid",
            validation_error=None,
        )

    async def test_missing_site_id_cache_falls_back_to_url_lookup(self):
        cached = {
            "site_id": 42,
            "api_url": "https://final.example/notices.json",
            "method_type": "GET",
        }
        with (
            patch(
                "dataController.selector.detect_api_auto.validate_public_url",
                return_value=SimpleNamespace(url="https://final.example/notices"),
            ),
            patch(
                "dataController.selector.detect_api_auto.notice_repo."
                "select_api_by_site_id",
                return_value=None,
            ) as select_by_site_id,
            patch(
                "dataController.selector.detect_api_auto.notice_repo.select_api",
                return_value=cached,
            ) as select_by_url,
            patch(
                "dataController.selector.detect_api_auto.notice_repo.update_site_crawl_state",
            ),
            patch(
                "dataController.selector.detect_api_auto.validate_candidate",
                new=AsyncMock(return_value=("passed", "fixture passed")),
            ),
        ):
            result = await find_api(
                "https://final.example/notices",
                site_id=42,
            )

        self.assertEqual(result["api_url"], cached["api_url"])
        self.assertFalse(result["_pending_persistence"])
        select_by_site_id.assert_called_once_with(42)
        select_by_url.assert_called_once_with("https://final.example/notices")

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


class ResponseBodyLimitRegressionTests(unittest.TestCase):
    def test_document_replay_uses_shared_policy_and_passes_semantic_gate(self):
        body = (FIXTURE_DIR / "notices.html").read_text(encoding="utf-8")
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "text/html; charset=UTF-8"}
        response.encoding = "utf-8"
        response.text = body

        with patch(
            "dataController.selector.detect_api_auto.safe_request",
            return_value=response,
        ) as request:
            candidate = {
                "api_url": "https://public.example/notices",
                "method_type": "GET",
                "source_kind": "document_html",
            }
            status, _ = _sync_validate_candidate(candidate)

        self.assertEqual(status, "passed")
        self.assertNotIn("max_response_bytes", request.call_args.kwargs)
        self.assertNotIn("max_transfer_bytes", request.call_args.kwargs)
        self.assertEqual(
            candidate["_validated_response_snapshot"]["body_text"],
            body,
        )
        self.assertEqual(
            candidate["_validated_response_snapshot"]["response_url"],
            "https://public.example/notices",
        )

    def test_youtube_posts_document_passes_semantic_gate(self):
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "text/html; charset=UTF-8"}
        response.encoding = "utf-8"
        response.text = _youtube_posts_html()

        with patch(
            "dataController.selector.detect_api_auto.safe_request",
            return_value=response,
        ):
            candidate = {
                "api_url": "https://www.youtube.com/@channel/posts",
                "method_type": "GET",
                "source_kind": "document_html",
            }
            status, reason = _sync_validate_candidate(candidate)

        self.assertEqual(status, "passed")
        self.assertIn("records=2", reason)
        self.assertEqual(
            candidate["validation_analysis"]["analysis_kind"],
            "youtube_yt_initial_data",
        )


class YouTubeCommunityExtractionRegressionTests(unittest.TestCase):
    def test_window_assignment_with_nested_json_is_extracted(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(
            _youtube_posts_html('window["ytInitialData"] ='),
            "lxml",
        )
        try:
            data = extract_yt_data(soup)
        finally:
            soup.decompose()

        self.assertIsNotNone(data)
        self.assertEqual(len(data["contents"]), 2)
        notices = parse_youtube_community_data(
            data,
            "https://www.youtube.com/@channel/posts",
        )
        self.assertEqual(len(notices), 2)
        self.assertEqual(notices[0]["url"], "https://www.youtube.com/post/post-1")


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

    def test_changed_content_hash_does_not_reset_retry_cap(self):
        decision = decide_observation(
            "new-content-hash",
            {
                "last_observed_hash": "previous-content-hash",
                "processing_status": "failed",
                "retry_count": 3,
            },
        )
        self.assertEqual(decision, "retry_exhausted")

    def test_changed_content_hash_still_respects_failure_backoff(self):
        decision = decide_observation(
            "new-content-hash",
            {
                "last_observed_hash": "previous-content-hash",
                "processing_status": "failed",
                "retry_count": 1,
                "next_retry_at": "2099-01-01T00:00:00+00:00",
            },
        )
        self.assertEqual(decision, "backoff")

    def test_retry_exhausted_marks_site_failed_without_invalidating_access(self):
        with patch(
            "dataController.scraper.scrape_auto.notice_repo."
            "update_site_crawl_state"
        ) as update_state:
            _update_site_after_skipped_observation(
                site_id=7,
                observation_decision="retry_exhausted",
                processing_state={
                    "processing_status": "failed",
                    "last_error": "공지 레코드 선택자를 찾지 못했습니다.",
                },
            )

        update_state.assert_called_once_with(
            7,
            crawl_status="failed",
            validation_status="valid",
            validation_error_code="NOTICE_EXTRACTION_FAILED",
            validation_error="공지 레코드 선택자를 찾지 못했습니다.",
        )

    def test_backoff_also_preserves_failed_collection_health(self):
        with patch(
            "dataController.scraper.scrape_auto.notice_repo."
            "update_site_crawl_state"
        ) as update_state:
            _update_site_after_skipped_observation(
                site_id=7,
                observation_decision="backoff",
                processing_state={"processing_status": "failed"},
            )

        update_state.assert_called_once_with(
            7,
            crawl_status="failed",
            validation_status="valid",
            validation_error_code="NOTICE_EXTRACTION_FAILED",
            validation_error=(
                "이전 공지 추출 실패로 다음 재시도 시각까지 대기합니다."
            ),
        )

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
                    "version": 6,
                    "source_type": "html",
                    "record_css": "ul.card_list > li",
                }
            },
        )
        self.assertEqual(decision, "unchanged")

    def test_old_notice_identity_rule_reprocesses_unchanged_source(self):
        decision = _refresh_notice_identity_decision(
            "unchanged",
            {
                "extractor_config": {
                    "version": 4,
                    "source_type": "html",
                }
            },
        )
        self.assertEqual(decision, "process")

    def test_current_notice_identity_rule_keeps_unchanged_decision(self):
        decision = _refresh_notice_identity_decision(
            "unchanged",
            {
                "extractor_config": {
                    "version": 4,
                    "source_type": "html",
                    "notice_identity_version": 2,
                }
            },
        )
        self.assertEqual(decision, "unchanged")

    def test_old_html_detail_url_base_reprocesses_unchanged_source(self):
        decision = _refresh_detail_url_base_decision(
            "unchanged",
            {
                "extractor_config": {
                    "format": "agent_extractor_v1",
                    "source_type": "html",
                    "notice_identity_version": 1,
                }
            },
        )
        self.assertEqual(decision, "process")

    def test_current_html_detail_url_base_keeps_unchanged_decision(self):
        decision = _refresh_detail_url_base_decision(
            "unchanged",
            {
                "extractor_config": {
                    "source_type": "html",
                    "detail_url_base_version": DETAIL_URL_BASE_VERSION,
                }
            },
        )
        self.assertEqual(decision, "unchanged")

    def test_notice_identity_version_is_persisted_after_success(self):
        api = {
            "extractor_config": {
                "version": 4,
                "source_type": "html",
            },
            "schema_hash": "schema-hash",
            "extractor_confidence": 0.96,
        }
        with patch(
            "dataController.scraper.scrape_auto.notice_repo.update_api_extractor"
        ) as update_extractor:
            _complete_notice_identity_upgrade(
                api,
                "https://public.example/notices",
            )

        self.assertEqual(
            api["extractor_config"]["notice_identity_version"],
            2,
        )
        update_extractor.assert_called_once()

    def test_large_semantic_to_extraction_drop_is_diagnostic(self):
        diagnostics = _extraction_coverage_diagnostics(
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
        self.assertEqual(diagnostics["semantic_record_count"], 9)
        self.assertEqual(diagnostics["extracted_record_count"], 1)
        self.assertEqual(
            diagnostics["reason_codes"],
            ["COVERAGE_MISMATCH"],
        )

    def test_matching_semantic_and_extraction_counts_are_accepted(self):
        diagnostics = _extraction_coverage_diagnostics(
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
        self.assertEqual(diagnostics, {})

    def test_large_extraction_expansion_is_diagnostic(self):
        diagnostics = _extraction_coverage_diagnostics(
            {
                "validation_analysis": {
                    "semantic_record_count": 20,
                }
            },
            ExtractionResult(
                status="success",
                notices=[
                    {"title": f"공지 {index}"}
                    for index in range(27)
                ],
                extractor_config=None,
                schema_hash=None,
                confidence=0.96,
                intermediate=None,
            ),
        )

        self.assertEqual(diagnostics["semantic_record_count"], 20)
        self.assertEqual(diagnostics["extracted_record_count"], 27)
        self.assertEqual(
            diagnostics["reason_codes"],
            ["OVER_EXTRACTION"],
        )

    def test_completion_keeps_evaluator_approved_count_mismatch(self):
        api = {
            "site_id": 7,
            "validation_analysis": {"semantic_record_count": 9},
        }
        result = ExtractionResult(
            status="success",
            notices=[{"title": "실제 대상 공지"}],
            extractor_config=None,
            schema_hash=None,
            confidence=0.96,
            intermediate=None,
        )

        structured = _apply_deterministic_result(
            api,
            "https://public.example/notices",
            result,
        )

        self.assertEqual(structured["status"], "success")
        self.assertEqual(structured["notices"], result.notices)
        self.assertEqual(
            api["_coverage_diagnostics"]["reason_codes"],
            ["COVERAGE_MISMATCH"],
        )


class RawHashCacheRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_robots_result_does_not_prevent_candidate_discovery(self):
        with (
            patch(
                "dataController.scraper.scrape_auto.expand_url",
                return_value="https://final.example/notices",
            ),
            patch(
                "dataController.scraper.scrape_auto.is_crawling_allowed",
                new=AsyncMock(return_value=False),
            ) as robots_check,
            patch(
                "dataController.scraper.scrape_auto.find_api",
                new=AsyncMock(return_value=None),
            ) as find_api,
            patch(
                "dataController.scraper.scrape_auto.notice_repo.update_site_crawl_state",
            ) as update_state,
        ):
            result = await run_full_scrape(
                "https://short.example/redirect",
                site_id=42,
            )

        robots_check.assert_not_awaited()
        find_api.assert_awaited_once_with(
            "https://final.example/notices",
            site_id=42,
        )
        update_state.assert_not_called()
        self.assertEqual(result["site_id"], 42)
        self.assertEqual(result["status"], "error")

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
        response.text = canonical

        api = {
            "site_id": 7,
            "api_id": 9,
            "api_url": "https://public.example/notices.json",
            "method_type": "GET",
            "headers": {},
            "payload": {},
            "extractor_config": {
                "version": 2,
                "source_type": "json",
                "notice_identity_version": 2,
            },
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
                "dataController.scraper.scrape_auto.notice_repo."
                "activate_site_after_successful_sync",
            ) as activate_site,
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
        activate_site.assert_called_once_with(7)
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
