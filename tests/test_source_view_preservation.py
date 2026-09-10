import json
import unittest

from bs4 import BeautifulSoup

from dataController.scraper.page_extractors import (
    build_html_source_views,
    extract_embedded_json_data,
    extract_javascript_hydration_data,
)


class SourceViewPreservationTests(unittest.TestCase):
    def test_strict_window_state_json_is_decoded_without_execution(self):
        soup = BeautifulSoup(
            """
            <script>
              window.__APP_STATE__ = {"items":[
                {"title":"첫 공지","createdAt":"2026-08-30","id":2},
                {"title":"둘째 공지","createdAt":"2026-08-29","id":1}
              ]};
            </script>
            """,
            "lxml",
        )
        try:
            value = extract_javascript_hydration_data(soup)
        finally:
            soup.decompose()

        self.assertEqual(len(value["items"]), 2)

    def test_next_flight_string_json_is_decoded_without_execution(self):
        payload = {
            "items": [
                {"title": "첫 공지", "publishedAt": "2026-08-30", "id": 2},
                {"title": "둘째 공지", "publishedAt": "2026-08-29", "id": 1},
            ]
        }
        flight_argument = json.dumps(
            [1, json.dumps(payload, ensure_ascii=False)],
            ensure_ascii=False,
        )
        soup = BeautifulSoup(
            f"<script>self.__next_f.push({flight_argument})</script>",
            "lxml",
        )
        try:
            value = extract_javascript_hydration_data(soup)
        finally:
            soup.decompose()

        self.assertEqual(len(value["items"]), 2)

    def test_javascript_expressions_are_not_evaluated_as_hydration(self):
        soup = BeautifulSoup(
            """
            <script>
              window.__STATE__ = buildState(fetch('/private'));
              window.__MENU__ = {items: [
                {title: '메뉴 1', id: 1}, {title: '메뉴 2', id: 2}
              ]};
            </script>
            """,
            "lxml",
        )
        try:
            value = extract_javascript_hydration_data(soup)
        finally:
            soup.decompose()

        self.assertIsNone(value)

    def test_repeated_hydration_records_are_promoted_to_json_source(self):
        soup = BeautifulSoup(
            """
            <html><body><div id="app"></div>
              <script type="application/json" id="app-state">
                {"items":[
                  {"title":"첫 공지","publishedAt":"2026-08-30","id":2},
                  {"title":"둘째 공지","publishedAt":"2026-08-29","id":1}
                ]}
              </script>
            </body></html>
            """,
            "lxml",
        )
        try:
            value = extract_embedded_json_data(soup)
        finally:
            soup.decompose()

        self.assertEqual(len(value["items"]), 2)

    def test_seo_json_ld_and_identifier_only_menu_data_are_not_promoted(self):
        soup = BeautifulSoup(
            """
            <script type="application/ld+json">
              {"itemListElement":[{"name":"메뉴 1"},{"name":"메뉴 2"}]}
            </script>
            <script type="application/json">
              {"items":[{"title":"메뉴 1","id":1},{"title":"메뉴 2","id":2}]}
            </script>
            """,
            "lxml",
        )
        try:
            value = extract_embedded_json_data(soup)
        finally:
            soup.decompose()

        self.assertIsNone(value)

    def test_raw_html_is_immutable_while_analysis_text_is_derived(self):
        raw_html = """
        <html><body>
          <script>window.secretStructure = {items: [1, 2]};</script>
          <nav>메뉴 링크</nav>
          <main><article><a href="/notice/1">첫 공지</a></article></main>
        </body></html>
        """

        views = build_html_source_views(raw_html)

        self.assertEqual(views.raw_html, raw_html)
        self.assertIn("window.secretStructure", views.raw_html)
        self.assertNotIn("window.secretStructure", views.analysis_text)
        self.assertIn("첫 공지", views.analysis_text)
        self.assertNotEqual(views.raw_hash, views.analysis_hash)
        self.assertEqual(views.metrics()["raw_chars"], len(raw_html))


if __name__ == "__main__":
    unittest.main()
