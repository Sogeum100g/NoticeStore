import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from dataController.scraper import scrape_auto


class NoDirectLlmNormalizationTests(unittest.TestCase):
    def test_scrape_pipeline_has_no_extraction_ai_fallback(self):
        self.assertFalse(
            hasattr(scrape_auto, "structure_notices_with_llm"),
            "크롤링 파이프라인이 원문 전체 LLM 정규화 함수를 노출합니다.",
        )
        self.assertFalse(
            hasattr(scrape_auto, "generate_and_validate_rule"),
            "크롤링 파이프라인이 AI 추출 규칙 fallback을 노출합니다.",
        )

    def test_data_processing_has_no_gemini_dependency(self):
        project_root = Path(__file__).resolve().parents[1]
        scraper_sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (project_root / "dataController" / "scraper").rglob("*.py")
        )

        self.assertNotIn("GEMINI_API_KEY_DATA_PROCESSING", scraper_sources)
        self.assertNotIn("google.genai", scraper_sources)
        self.assertNotIn("from google import genai", scraper_sources)


class FailedExtractionPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_unrecognized_source_is_failed_without_fabricated_notices(self):
        response = Mock()
        response.headers = {"Content-Type": "text/html"}
        response.apparent_encoding = "utf-8"
        response.encoding = "utf-8"
        response.text = "<html><body><p>목록 구조가 없는 페이지</p></body></html>"
        response.raise_for_status.return_value = None

        api = {
            "site_id": 7,
            "api_id": 9,
            "api_url": "https://public.example/unrecognized",
            "method_type": "GET",
            "headers": {},
            "payload": {},
            "_pending_persistence": False,
        }

        with (
            patch(
                "dataController.scraper.scrape_auto.expand_url",
                return_value="https://public.example/unrecognized",
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
                "dataController.scraper.scrape_auto.safe_request",
                return_value=response,
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo.select_processing_state",
                return_value={},
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo.create_crawl_run",
                return_value=12,
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo.update_api_processing_state",
            ) as update_processing,
            patch(
                "dataController.scraper.scrape_auto.notice_repo.update_site_crawl_state",
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo.finish_crawl_run",
            ),
        ):
            result = await scrape_auto.run_full_scrape(
                "https://public.example/unrecognized"
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["notices"], [])
        self.assertIn(
            "AI fallback을 사용하지 않습니다",
            result["error_msg"],
        )
        self.assertEqual(
            update_processing.call_args.kwargs["status"],
            "failed",
        )


if __name__ == "__main__":
    unittest.main()
