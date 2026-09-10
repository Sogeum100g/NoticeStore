import unittest

from bs4 import BeautifulSoup

from dataController.scraper.declarative_rule_executor import execute_extractor_rule
from dataController.scraper.deterministic_extractor import (
    extract_notices_deterministically,
)
from dataController.scraper.extraction_agent_contracts import ExtractorRuleV1
from dataController.scraper.html_navigation import resolve_html_navigation_url
from dataController.scraper.rule_candidate_adapter import (
    build_rule_based_candidate,
)


class HtmlNavigationResolverTests(unittest.TestCase):
    def test_resolves_literal_onclick_and_simple_function_wrapper(self):
        html = """
        <div>
          <button id="literal" onclick="location.href='/notice/10'">공지 10</button>
          <a id="wrapped" href="javascript:openNotice('11', 'general')">
            공지 11
          </a>
        </div>
        <script>
          function openNotice(id, category) {
            window.open('/notice/view?id=' + id + '&category=' + category, '_blank');
          }
        </script>
        """
        soup = BeautifulSoup(html, "lxml")
        self.assertEqual(
            resolve_html_navigation_url(
                "https://public.example/notices",
                soup.select_one("#literal"),
                document=soup,
            ),
            "https://public.example/notice/10",
        )
        self.assertEqual(
            resolve_html_navigation_url(
                "https://public.example/notices",
                soup.select_one("#wrapped"),
                document=soup,
            ),
            "https://public.example/notice/view?id=11&category=general",
        )

    def test_resolves_data_attributes_through_jquery_form_submission(self):
        html = """
        <form id="searchForm" method="post">
          <input type="hidden" id="noticeId" name="noticeId">
          <input type="hidden" id="category" name="category">
        </form>
        <a class="noticeInfoBtn" href="javascript:"
           data-id1="N-101" data-id2="housing">주택 공고</a>
        <script>
          $(".noticeInfoBtn").click(function(e) {
            var noticeId = $(this).attr('data-id1');
            var category = $(this).attr('data-id2');
            $("#noticeId").val(noticeId);
            $("#category").val(category);
            formSubmit('detail');
          });
          function formSubmit(mode) {
            if (mode == 'search') {
              $("#searchForm").attr('action', '/notice/list.do').submit();
            } else {
              $("#searchForm").attr('action', '/notice/detailInfo.do').submit();
            }
          }
        </script>
        """
        soup = BeautifulSoup(html, "lxml")
        self.assertEqual(
            resolve_html_navigation_url(
                "https://public.example/notice/list.do",
                soup.select_one(".noticeInfoBtn"),
                document=soup,
            ),
            (
                "https://public.example/notice/detailInfo.do"
                "?noticeId=N-101&category=housing"
            ),
        )


class NavigationRuleExecutionTests(unittest.TestCase):
    def test_navigation_source_executes_for_links_and_buttons(self):
        html = """
        <ul class="notices">
          <li><button class="title" onclick="location.href='/n/2'">두 번째 공지</button></li>
          <li><button class="title" data-url="/n/1">첫 번째 공지</button></li>
        </ul>
        """
        rule = ExtractorRuleV1.model_validate(
            {
                "version": 1,
                "source_type": "html",
                "record_selector": "ul.notices > li",
                "fields": {
                    "title": {
                        "kind": "html",
                        "selector": "button.title",
                        "source": "text",
                        "transforms": ["normalize_space"],
                    },
                    "detail_url": {
                        "kind": "html",
                        "selector": "button.title",
                        "source": "navigation",
                        "transforms": [],
                    },
                },
                "evidence_ids": ["button-list"],
            }
        )
        result = execute_extractor_rule(
            html,
            rule=rule,
            base_url="https://public.example/notices",
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(
            [notice["detail_url"] for notice in result.notices],
            ["https://public.example/n/2", "https://public.example/n/1"],
        )

    def test_legacy_href_rule_falls_back_to_navigation_resolution(self):
        html = """
        <table><tbody>
          <tr><td><a class="info" href="javascript:" onclick="goView('A1')">첫 공지사항</a></td></tr>
          <tr><td><a class="info" href="javascript:" onclick="goView('A2')">둘째 공지사항</a></td></tr>
        </tbody></table>
        <script>
          function goView(id) { location.href = '/view.do?id=' + id; }
        </script>
        """
        rule = ExtractorRuleV1.model_validate(
            {
                "version": 1,
                "source_type": "html",
                "record_selector": "table tbody tr",
                "fields": {
                    "title": {
                        "kind": "html",
                        "selector": "a.info",
                        "source": "text",
                        "transforms": ["normalize_space"],
                    },
                    "detail_url": {
                        "kind": "html",
                        "selector": "a.info",
                        "source": "attribute",
                        "attribute": "href",
                        "transforms": ["urljoin"],
                    },
                },
                "evidence_ids": ["legacy-link-list"],
            }
        )
        result = execute_extractor_rule(
            html,
            rule=rule,
            base_url="https://public.example/list.do",
        )
        self.assertEqual(
            [notice["detail_url"] for notice in result.notices],
            [
                "https://public.example/view.do?id=A1",
                "https://public.example/view.do?id=A2",
            ],
        )

    def test_deterministic_table_extraction_uses_page_level_form_handler(self):
        html = """
        <form id="srchForm" method="post">
          <input type="hidden" id="panId" name="panId">
          <input type="hidden" id="kind" name="kind">
        </form>
        <table><tbody>
          <tr>
            <td><a class="infoBtn" href="javascript:" data-id1="BN-2"
                   data-id2="01">두 번째 공급 공고</a></td>
            <td>2026.08.27</td>
          </tr>
          <tr>
            <td><a class="infoBtn" href="javascript:" data-id1="BN-1"
                   data-id2="02">첫 번째 공급 공고</a></td>
            <td>2026.08.26</td>
          </tr>
        </tbody></table>
        <script>
          $(".infoBtn").click(function() {
            var panId = $(this).attr('data-id1');
            var kind = $(this).attr('data-id2');
            $("#panId").val(panId);
            $("#kind").val(kind);
            goDetail();
          });
          function goDetail() {
            $("#srchForm").attr('action', '/notice/selectInfo.do').submit();
          }
        </script>
        """
        result = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url="https://public.example/notice/selectList.do",
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(
            [notice["detail_url"] for notice in result.notices],
            [
                "https://public.example/notice/selectInfo.do?kind=01&panId=BN-2",
                "https://public.example/notice/selectInfo.do?kind=02&panId=BN-1",
            ],
        )
        rule = build_rule_based_candidate(html, result)
        self.assertIsNotNone(rule)
        self.assertEqual(rule.fields.detail_url.source, "navigation")
        replay = execute_extractor_rule(
            html,
            rule=rule,
            base_url="https://public.example/notice/selectList.do",
        )
        self.assertEqual(
            [notice["detail_url"] for notice in replay.notices],
            [notice["detail_url"] for notice in result.notices],
        )


if __name__ == "__main__":
    unittest.main()
