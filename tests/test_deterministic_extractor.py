import json
import unittest
from pathlib import Path

from dataController.scraper.deterministic_extractor import (
    extract_notices_deterministically,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class DeterministicJsonExtractorTests(unittest.TestCase):
    def test_json_paths_and_detail_urls_are_preserved(self):
        raw = json.loads(
            (FIXTURE_DIR / "notices.json").read_text(encoding="utf-8")
        )
        result = extract_notices_deterministically(
            raw,
            content_type="application/json",
            base_url="https://public.example/notices",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.extractor_config["records_path"], "$.response.items")
        self.assertEqual(result.notices[0]["external_id"], "notice-101")
        self.assertEqual(
            result.notices[0]["detail_url"],
            "https://public.example/notices/101",
        )
        first_field = result.intermediate["records"][0]["fields"]["title"]
        self.assertEqual(first_field["json_path"], "$.response.items[0].title")

    def test_saved_json_rule_returns_valid_empty_without_llm(self):
        result = extract_notices_deterministically(
            {"response": {"items": []}},
            content_type="application/json",
            base_url="https://public.example/notices",
            extractor_config={
                "version": 1,
                "source_type": "json",
                "records_path": "$.response.items",
                "fields": {"title": "title"},
            },
        )
        self.assertEqual(result.status, "valid_empty")
        self.assertEqual(result.notices, [])

    def test_jsonp_is_extracted_without_full_text_llm(self):
        raw = (FIXTURE_DIR / "notices.jsonp").read_text(encoding="utf-8")
        result = extract_notices_deterministically(
            raw,
            content_type="application/javascript",
            base_url="https://public.example/notices",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.notices), 2)
        self.assertEqual(result.notices[0]["title"], "첫 번째 채용 공고 안내")
        self.assertEqual(result.notices[0]["published_at"], "2026-07-27")

    def test_duplicate_records_are_removed_by_stable_identity(self):
        result = extract_notices_deterministically(
            {
                "items": [
                    {
                        "id": "notice-1",
                        "title": "새 공지",
                        "date": "2026-07-27",
                    },
                    {
                        "id": "notice-1",
                        "title": " 새   공지 (표시 변형) ",
                        "date": "2026-07-27",
                    },
                    {
                        "id": "notice-2",
                        "title": "다른 공지",
                        "date": "2026-07-26",
                    },
                ]
            },
            content_type="application/json",
            base_url="https://public.example/notices",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(
            [notice["external_id"] for notice in result.notices],
            ["notice-1", "notice-2"],
        )


class DeterministicHtmlExtractorTests(unittest.TestCase):
    def test_anchor_relationship_is_preserved(self):
        html = (FIXTURE_DIR / "notices.html").read_text(encoding="utf-8")
        result = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url="https://public.example/board/list",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.notices[0]["title"], "첫 번째 서버 점검 공지")
        self.assertEqual(
            result.notices[0]["detail_url"],
            "https://public.example/notice/301",
        )
        self.assertEqual(
            result.intermediate["records"][0]["links"][0]["candidate_id"],
            "r0_a0",
        )

    def test_group_date_and_semantic_author_are_inherited(self):
        html = """
        <html><body>
          <section>
            <time datetime="2026-07-24T17:48:00Z">24 July 2026</time>
            <article>
              <h2><a href="/changes/one">First platform release announcement</a></h2>
              <span class="author">Platform Team</span>
            </article>
            <article>
              <h2><a href="/changes/two">Second workflow release announcement</a></h2>
              <span class="author">Workflow Team</span>
            </article>
          </section>
        </body></html>
        """
        result = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url="https://public.example/changelog",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.notices[0]["published_at"],
            "2026-07-24T17:48:00Z",
        )
        self.assertEqual(result.notices[0]["author"], "Platform Team")


if __name__ == "__main__":
    unittest.main()
