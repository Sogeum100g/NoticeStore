import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from dataController.scraper.dcinside_source import (
    gallery_list_id, preserve_list_filter, validate_list_response,
)
from dataController.selector.detect_api_auto import (
    _prepare_list_candidate, _sync_validate_candidate, find_api,
)


TARGET = "https://m.dcinside.com/board/chicken?recommend=1"
SOURCE = "https://gall.dcinside.com/board/lists/?id=chicken"
FILTERED = SOURCE + "&exception_mode=recommend"
SELECTED_TAB = "<button class='on' onclick=\"listKindTab('recommend','list');return false;\">개념글</button>"


class DCInsideSourceTests(unittest.TestCase):
    def test_desktop_filter_preserves_gallery_route_and_other_parameters(self):
        for prefix in ("", "mgallery/", "mini/"):
            source = f"https://gall.dcinside.com/{prefix}board/lists/?id=chicken&page=2"
            result = preserve_list_filter(TARGET, source)
            self.assertEqual(urlsplit(result).path, urlsplit(source).path)
            self.assertEqual(parse_qs(urlsplit(result).query), {
                "id": ["chicken"], "page": ["2"], "exception_mode": ["recommend"],
            })
            self.assertEqual(preserve_list_filter(TARGET, result), result)

    def test_unrelated_galleries_posts_and_hosts_are_not_rewritten(self):
        for source in (
            "https://gall.dcinside.com/board/lists/?id=hair",
            "https://gall.dcinside.com/board/view/?id=chicken&no=1",
            "https://gall.dcinside.com.evil.test/board/lists/?id=chicken",
            "https://example.com/board/lists/?id=chicken",
        ):
            self.assertEqual(preserve_list_filter(TARGET, source), source)
            self.assertFalse(validate_list_response(TARGET, source, SELECTED_TAB))
        self.assertIsNone(gallery_list_id("https://m.dcinside.com/board/chicken/123"))
        self.assertIsNone(gallery_list_id(SOURCE + "&id=hair"))

    def test_query_alone_does_not_prove_server_applied_filter(self):
        self.assertTrue(validate_list_response(TARGET, FILTERED, SELECTED_TAB))
        self.assertFalse(validate_list_response(TARGET, FILTERED, SELECTED_TAB.replace("class='on'", "class=''")))
        self.assertFalse(validate_list_response(TARGET, SOURCE, SELECTED_TAB))

    def test_replay_fetches_filtered_content_and_rejects_filter_loss(self):
        html = (Path(__file__).parent / "fixtures" / "dcinside_board.html").read_text()
        html = html.replace("id=hair", "id=chicken").replace("<body>", "<body>" + SELECTED_TAB)
        candidate = {"api_url": SOURCE, "source_kind": "document_html", "_validated_response_snapshot": {"body_text": "unfiltered"}}
        self.assertTrue(_prepare_list_candidate(candidate, TARGET))
        self.assertNotIn("_validated_response_snapshot", candidate)
        response = SimpleNamespace(status_code=200, url=FILTERED, text=html,
                                   headers={"Content-Type": "text/html"}, encoding="utf-8", close=lambda: None)
        with patch("dataController.selector.detect_api_auto.safe_request", return_value=response) as request:
            status, _ = _sync_validate_candidate(candidate)
            self.assertEqual(status, "passed")
            self.assertEqual(request.call_args.args[2], FILTERED)
            self.assertIn(SELECTED_TAB, candidate["_validated_response_snapshot"]["body_text"])
            response.url = SOURCE
            status, reason = _sync_validate_candidate(candidate)
            self.assertEqual(status, "semantic_failed")
            self.assertIn("개념글", reason)


class DCInsideCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_unfiltered_api_is_corrected_before_cache_validation(self):
        with (
            patch("dataController.selector.detect_api_auto.validate_public_url", return_value=SimpleNamespace(url=TARGET)),
            patch("repositories.notice_repo.select_api_by_site_id", return_value={"site_id": 48, "api_url": SOURCE}),
            patch("repositories.notice_repo.update_site_crawl_state"),
            patch("dataController.selector.detect_api_auto.validate_candidate", new=AsyncMock(return_value=("passed", "ok"))) as validate,
            patch("dataController.selector.detect_api_auto.collect_candidates", new=AsyncMock()) as collect,
        ):
            result = await find_api(TARGET, site_id=48)
        self.assertEqual(validate.call_args.args[0]["api_url"], FILTERED)
        self.assertTrue(result["_pending_persistence"])
        self.assertEqual(result["site_id"], 48)
        collect.assert_not_awaited()
