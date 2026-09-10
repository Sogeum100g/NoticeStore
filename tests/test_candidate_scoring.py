import unittest
from pathlib import Path

from dataController.selector.candidate_analyzer import analyze_candidate_body
from dataController.selector.candidate_ranker import build_candidate_pool, rank_candidates


TARGET_URL = "https://maplestory.nexon.com/News/Notice"
FIXTURE_DIR = Path(__file__).parent / "fixtures"


def make_candidate(
    *,
    api_index,
    api_url,
    source_kind,
    resource_type,
    content_type,
    body_shape,
    body,
    has_callback_param=False,
):
    analysis = analyze_candidate_body(
        body,
        body_shape=body_shape,
        content_type=content_type,
    )
    return {
        "api_index": api_index,
        "method_type": "GET",
        "type": resource_type,
        "source_kind": source_kind,
        "api_url": api_url,
        "content_type": content_type,
        "body_shape": body_shape,
        "sample": analysis["semantic_sample"],
        "data_key_hits": analysis["data_key_hits"],
        "semantic_record_count": analysis["semantic_record_count"],
        "title_date_pair_count": analysis["title_date_pair_count"],
        "has_repeated_records": analysis["has_repeated_records"],
        "has_notice_terms": analysis["has_notice_terms"],
        "has_callback_param": has_callback_param,
        "payload": {},
        "length": len(body),
    }


class CandidateAnalyzerTests(unittest.TestCase):
    def test_javascript_hydration_is_visible_to_candidate_gate(self):
        analysis = analyze_candidate_body(
            """
            <script>
              window.__APP_STATE__ = {"items":[
                {"title":"첫 공지","createdAt":"2026-08-30","id":2},
                {"title":"둘째 공지","createdAt":"2026-08-29","id":1}
              ]};
            </script>
            """,
            body_shape="html",
            content_type="text/html",
        )

        self.assertEqual(analysis["analysis_kind"], "javascript_hydration")
        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 2)

    def test_hydration_json_is_visible_to_candidate_semantic_gate(self):
        analysis = analyze_candidate_body(
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
            body_shape="html",
            content_type="text/html",
        )

        self.assertEqual(analysis["analysis_kind"], "embedded_json")
        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 2)

    def test_hanwha_recruitment_fields_are_semantic_records(self):
        body = (FIXTURE_DIR / "hanwha_recruit.json").read_text(
            encoding="utf-8"
        )

        analysis = analyze_candidate_body(
            body,
            body_shape="json_object",
            content_type="application/json",
        )

        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 2)
        self.assertEqual(analysis["title_date_pair_count"], 2)

    def test_machine_dates_in_title_attributes_are_record_evidence(self):
        body = (FIXTURE_DIR / "dcinside_board.html").read_text(
            encoding="utf-8"
        )

        analysis = analyze_candidate_body(
            body,
            body_shape="html",
            content_type="text/html",
        )

        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 3)
        self.assertNotIn("게시판 이용 설문", analysis["semantic_sample"])

    def test_job_cards_outrank_ui_articles_and_footer_dates(self):
        body = (FIXTURE_DIR / "jobkorea_recruit.html").read_text(
            encoding="utf-8"
        )

        analysis = analyze_candidate_body(
            body,
            body_shape="html",
            content_type="text/html",
        )

        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 3)
        self.assertIn("넥토리얼", analysis["semantic_sample"])
        self.assertNotIn("리스트 정렬 순서 선택", analysis["semantic_sample"])

    def test_footer_dates_do_not_promote_undated_ui_articles(self):
        analysis = analyze_candidate_body(
            """
            <article><h2>검색 조건 선택</h2><a href="javascript:void(0)">전체</a></article>
            <article><h2>카테고리 선택</h2><a href="javascript:void(0)">분류</a></article>
            <footer>개인정보처리방침 개정 18.05.09 / 상담 09:00 ~ 18:00</footer>
            """,
            body_shape="html",
            content_type="text/html",
        )

        self.assertFalse(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 0)

    def test_config_updated_is_not_mistaken_for_date_key(self):
        analysis = analyze_candidate_body(
            '{"title":"Airbridge SDK config","lastUpdated":"2026-07-26"}',
            body_shape="json_object",
            content_type="application/json",
        )

        self.assertIn("title", analysis["data_key_hits"])
        self.assertNotIn("date", analysis["data_key_hits"])
        self.assertFalse(analysis["has_repeated_records"])

    def test_structured_notice_list_has_repeated_record_evidence(self):
        body = """
        {
          "items": [
            {"title": "첫 번째 공지", "date": "2026-07-26", "url": "/1"},
            {"title": "두 번째 공지", "date": "2026-07-25", "url": "/2"}
          ]
        }
        """
        analysis = analyze_candidate_body(
            body,
            body_shape="json_object",
            content_type="application/json",
        )

        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 2)
        self.assertEqual(analysis["title_date_pair_count"], 2)

    def test_server_rendered_html_has_repeated_record_evidence(self):
        body = """
        <html><body>
          <h1>공지사항</h1>
          <ul>
            <li><a href="/News/Notice/1">첫 번째 점검 완료 안내</a><time>2026.07.26</time></li>
            <li><a href="/News/Notice/2">두 번째 패치 완료 안내</a><time>2026.07.25</time></li>
            <li><a href="/News/Notice/3">세 번째 이용 안내 공지</a><time>2026.07.24</time></li>
          </ul>
        </body></html>
        """
        analysis = analyze_candidate_body(
            body,
            body_shape="html",
            content_type="text/html",
        )

        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 3)
        self.assertIn("title", analysis["data_key_hits"])
        self.assertIn("date", analysis["data_key_hits"])

    def test_server_rendered_table_with_two_digit_year_dates(self):
        body = """
        <html><body><h1>공지사항</h1>
          <table class="board-table"><tbody>
            <tr>
              <td>528</td>
              <td class="b-td-left"><div class="b-title-box">
                <a href="?mode=view&amp;articleNo=595367">첫 번째 특별 장학생 결과 발표</a>
                <span class="b-writer">소프트웨어중심대학</span>
                <span class="b-date">26.08.24</span>
              </div></td>
              <td>소프트웨어중심대학</td><td>26.08.24</td><td>7</td>
            </tr>
            <tr>
              <td>527</td>
              <td class="b-td-left"><div class="b-title-box">
                <a href="?mode=view&amp;articleNo=595119">두 번째 활동비 지급 서류 제출 안내</a>
                <span class="b-writer">소프트웨어중심대학</span>
                <span class="b-date">26.08.23</span>
              </div></td>
              <td>소프트웨어중심대학</td><td>26.08.23</td><td>12</td>
            </tr>
          </tbody></table>
        </body></html>
        """
        analysis = analyze_candidate_body(
            body,
            body_shape="html",
            content_type="text/html",
        )

        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 2)
        self.assertEqual(analysis["data_key_hits"], ["date", "list", "title"])

    def test_english_month_dates_have_repeated_record_evidence(self):
        body = """
        <html><body>
          <article>
            <h2><a href="/weblog/2026/jul/24/one/">See You in Chicago in One Month!</a></h2>
            <p>Posted by DjangoCon Organizers on July 24, 2026</p>
          </article>
          <article>
            <h2><a href="/weblog/2026/jul/22/two/">Django release candidate released</a></h2>
            <p>Posted by Django Team on July 22, 2026</p>
          </article>
          <aside>
            <ul>
              <li><a href="/weblog/2026/jul/">July 2026</a></li>
              <li><a href="/weblog/2026/jun/">June 2026</a></li>
            </ul>
          </aside>
        </body></html>
        """
        analysis = analyze_candidate_body(
            body,
            body_shape="html",
            content_type="text/html",
        )

        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 2)
        self.assertIn("date", analysis["data_key_hits"])

    def test_time_datetime_attributes_are_date_evidence(self):
        body = """
        <html><body>
          <article><a href="/one">First framework release announcement</a>
            <time datetime="2026-07-24">24 Jul</time></article>
          <article><a href="/two">Second framework release announcement</a>
            <time datetime="2026-07-22T10:00:00Z">22 Jul</time></article>
        </body></html>
        """
        analysis = analyze_candidate_body(
            body,
            body_shape="html",
            content_type="text/html",
        )

        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 2)

    def test_article_cards_with_abbreviated_english_dates(self):
        body = """
        <html><body>
          <article>
            <div class="changelog-item-content">
              <h3><time datetime="2026-07-24">Jul.24</time><span>Release</span></h3>
              <a href="/changelog/first" class="changelog-item-title">
                First product release is now generally available
              </a>
            </div>
          </article>
          <article>
            <div class="changelog-item-content">
              <h3><time datetime="2026-07-23">Jul.23</time><span>Improvement</span></h3>
              <a href="/changelog/second" class="changelog-item-title">
                Second product improvement enters public preview
              </a>
            </div>
          </article>
        </body></html>
        """
        analysis = analyze_candidate_body(
            body,
            body_shape="html",
            content_type="text/html",
        )

        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 2)
        self.assertEqual(
            analysis["semantic_sample"],
            (
                "First product release is now generally available | "
                "Second product improvement enters public preview"
            ),
        )

    def test_articles_can_share_a_group_date_header(self):
        body = """
        <html><body>
          <section>
            <time datetime="2026-07-24T17:48:00Z">24 July</time>
            <ul>
              <li><article><a href="/changelog/first">
                First platform capability is now in public beta
              </a></article></li>
              <li><article><a href="/changelog/second">
                Second workflow improvement is generally available
              </a></article></li>
              <li><article><a href="/changelog/third">
                Third dashboard feature supports longer operations
              </a></article></li>
            </ul>
          </section>
        </body></html>
        """
        analysis = analyze_candidate_body(
            body,
            body_shape="html",
            content_type="text/html",
        )

        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 3)
        self.assertIn("date", analysis["data_key_hits"])
        self.assertIn("list", analysis["data_key_hits"])

    def test_repeated_articles_without_any_date_do_not_pass(self):
        body = """
        <html><body>
          <article><a href="/one">First undated editorial story</a></article>
          <article><a href="/two">Second undated editorial story</a></article>
        </body></html>
        """
        analysis = analyze_candidate_body(
            body,
            body_shape="html",
            content_type="text/html",
        )

        self.assertFalse(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 0)

    def test_article_heading_is_preferred_over_long_card_link_text(self):
        long_description = "Detailed product explanation " * 20
        body = f"""
        <html><body>
          <time datetime="2026-07-24">24 July</time>
          <article><a href="/one"><h2>First concise release title</h2>
            <p>{long_description}</p></a></article>
          <article><a href="/two"><h2>Second concise release title</h2>
            <p>{long_description}</p></a></article>
        </body></html>
        """
        analysis = analyze_candidate_body(
            body,
            body_shape="html",
            content_type="text/html",
        )

        self.assertTrue(analysis["has_repeated_records"])
        self.assertEqual(analysis["semantic_record_count"], 2)
        self.assertEqual(
            analysis["semantic_sample"],
            "First concise release title | Second concise release title",
        )

class CandidateRankingRegressionTests(unittest.TestCase):
    def test_maplestory_document_outranks_airbridge_config_and_jsonp_noise(self):
        notice_html = """
        <html><body><h1>공지사항</h1>
          <ul>
            <li><a href="/News/Notice/1">토스페이 결제 할인 안내 공지</a><span>2026.07.26</span></li>
            <li><a href="/News/Notice/2">마이너 패치 완료 안내 공지</a><span>2026.07.25</span></li>
            <li><a href="/News/Notice/3">전체 월드 점검 완료 안내</a><span>2026.07.24</span></li>
          </ul>
        </body></html>
        """
        airbridge_config = (
            '{"title":"Airbridge SDK config","lastUpdated":"2026-07-26",'
            '"features":{"tracking":true}}'
        )
        jsonp_noise = "callback(" + '{"authenticated":false,"service":"login"}' + ")"

        candidates = [
            make_candidate(
                api_index=13,
                api_url="https://config.airbridge.io/v1/web/apps/maplestory",
                source_kind="xhr_json",
                resource_type="xhr",
                content_type="application/json",
                body_shape="json_object",
                body=airbridge_config,
            ),
            make_candidate(
                api_index=3,
                api_url="https://logins.nexon.com/login/page/ngb_login.aspx",
                source_kind="jsonp_javascript",
                resource_type="document",
                content_type="application/javascript",
                body_shape="jsonp_wrapper",
                body=jsonp_noise,
                has_callback_param=True,
            ),
            make_candidate(
                api_index=1,
                api_url=TARGET_URL,
                source_kind="document_html",
                resource_type="document",
                content_type="text/html",
                body_shape="html",
                body=notice_html,
            ),
        ]

        ranked = rank_candidates(candidates, TARGET_URL)

        self.assertEqual(ranked[0]["api_index"], 1)
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])
        self.assertTrue(ranked[0]["features"]["is_exact_target"])
        self.assertTrue(ranked[0]["features"]["has_repeated_records"])

    def test_exact_target_is_reserved_in_four_candidate_pool(self):
        ranked = [
            {
                "api_index": index,
                "api_url": f"https://external{index}.example/api",
                "score": 100 - index,
                "features": {
                    "is_exact_target": False,
                    "is_same_host": False,
                    "has_repeated_records": False,
                    "looks_like_non_content": False,
                },
            }
            for index in range(2, 7)
        ]
        ranked.append(
            {
                "api_index": 1,
                "api_url": TARGET_URL,
                "score": 1,
                "features": {
                    "is_exact_target": True,
                    "is_same_host": True,
                    "has_repeated_records": True,
                    "looks_like_non_content": False,
                },
            }
        )

        pool = build_candidate_pool(ranked, TARGET_URL, limit=4)

        self.assertEqual(len(pool), 4)
        self.assertIn(1, {item["api_index"] for item in pool})


if __name__ == "__main__":
    unittest.main()
