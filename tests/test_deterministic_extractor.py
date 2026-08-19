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

    def test_camel_case_job_records_and_derived_detail_urls(self):
        result = extract_notices_deterministically(
            {
                "jobList": [
                    {
                        "realId": "P-14472",
                        "jobOfferTitle": "AI 추론 효율화 Engineer",
                        "regDate": "2026-06-12T17:24:29",
                        "companyName": "카카오",
                    },
                    {
                        "realId": "P-14469",
                        "jobOfferTitle": "AI Platform Engineer",
                        "regDate": "2026-06-11T09:34:19",
                        "companyName": "카카오",
                    },
                ]
            },
            content_type="application/json",
            base_url=(
                "https://careers.kakao.com/jobs"
                "?company=KAKAO&part=TECHNOLOGY&page=1"
            ),
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.notices), 2)
        self.assertEqual(result.extractor_config["records_path"], "$.jobList")
        self.assertEqual(result.notices[0]["external_id"], "P-14472")
        self.assertEqual(result.notices[0]["author"], "카카오")
        self.assertEqual(
            result.notices[0]["detail_url"],
            (
                "https://careers.kakao.com/jobs/P-14472"
                "?company=KAKAO&part=TECHNOLOGY&page=1"
            ),
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

    def test_target_board_group_wins_over_event_banner_and_date_link(self):
        html = """
        <html><body>
          <ul class="event_all_banner">
            <li>
              <dl>
                <dt><a href="/News/Event/1364">[미니게임] - 울티마 스쿼드</a></dt>
                <dd><a href="/News/Event/1364">
                  2026.07.23 (목) ~ 2026.08.19 (수) 오후 11시59분
                </a></dd>
              </dl>
            </li>
            <li>
              <dl>
                <dt><a href="/News/Event/1363">상인단의 물자 지원 II</a></dt>
                <dd><a href="/News/Event/1363">
                  2026.07.23 (목) ~ 2026.09.16 (수) 오후 11시59분
                </a></dd>
              </dl>
            </li>
          </ul>
          <div class="news_board">
            <ul>
              <li>
                <p><a href="/News/Notice/All/149615">
                  <span>울티마 스쿼드 오류 관련 안내</span>
                </a></p>
                <div><dd>2026.07.29</dd></div>
              </li>
              <li>
                <p><a href="/News/Notice/All/149614">
                  <span>결제 서비스 점검 안내</span>
                </a></p>
                <div><dd>2026.07.28</dd></div>
              </li>
            </ul>
          </div>
        </body></html>
        """

        result = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url="https://maplestory.nexon.com/News/Notice",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.extractor_config["version"], 4)
        self.assertIn("news_board", result.extractor_config["record_css"])
        self.assertEqual(
            [notice["title"] for notice in result.notices],
            ["울티마 스쿼드 오류 관련 안내", "결제 서비스 점검 안내"],
        )

    def test_v1_broad_html_rule_is_rediscovered(self):
        html = """
        <html><body><div class="notice_board"><ul>
          <li><a href="/board/1">첫 번째 공지</a><time>2026.07.29</time></li>
          <li><a href="/board/2">두 번째 공지</a><time>2026.07.28</time></li>
        </ul></div></body></html>
        """

        result = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url="https://public.example/board",
            extractor_config={
                "version": 1,
                "source_type": "html",
                "record_css": "li",
            },
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.extractor_config["version"], 4)
        self.assertNotEqual(result.extractor_config["record_css"], "li")

    def test_top_level_samsung_job_fragments_are_extracted(self):
        html = """
        <input class="divCnt" data-max="1" data-value="3" type="hidden">
        <li>
          <div><a data-value="22,749" href="/#none">
            <p class="company">삼성중공업</p>
            <h3 class="title">경력사원 채용(운반선 설계, 구매, PM)</h3>
            <p class="info"><span>경력</span>
              <span class="period">2026.07.29 ~ 2026.08.11</span>
            </p>
          </a></div>
        </li>
        <li>
          <div><a data-value="22,762" href="/#none">
            <p class="company">삼성중공업</p>
            <h3 class="title">경력사원 채용(하이테크)</h3>
            <p class="info"><span>경력</span>
              <span class="period">2026.07.28 ~ 2026.08.10</span>
            </p>
          </a></div>
        </li>
        """

        result = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url="https://www.samsungcareers.com/hr/",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.notices), 2)
        self.assertEqual(result.notices[0]["author"], "삼성중공업")
        self.assertEqual(result.notices[0]["external_id"], "22749")
        self.assertEqual(
            result.notices[0]["detail_url"],
            "https://www.samsungcareers.com/hr/?no=22749",
        )
        self.assertEqual(result.notices[0]["published_at"], "2026-07-29")

    def test_placeholder_card_links_use_onclick_record_ids(self):
        html = """
        <div class="card_wrap">
          <ul class="card_list">
            <li class="card_item">
              <a class="card_link" href="#n" onclick="show('30005184')">
                <h4 class="card_title">[네이버랩스] Frontend Developer</h4>
                <dl><dd>2026.07.21 ~ 2026.08.03</dd></dl>
              </a>
            </li>
            <li class="card_item">
              <a class="card_link" href="#n" onclick="show(30005176)">
                <h4 class="card_title">[네이버랩스] Generative AI Engineer</h4>
                <dl><dd>2026.07.20 ~ 2026.08.03</dd></dl>
              </a>
            </li>
            <li class="card_item">
              <a class="card_link" href="#n" onclick="show('30005164')">
                <h4 class="card_title">[SNOW] IT 보안 기술 담당</h4>
                <dl><dd>2026.07.15 ~ 2026.08.03</dd></dl>
              </a>
            </li>
          </ul>
        </div>
        """

        result = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url=(
                "https://recruit.navercorp.com/rcrt/list.do"
                "?srchClassCd=1000000"
            ),
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.notices), 3)
        self.assertEqual(
            [notice["external_id"] for notice in result.notices],
            ["30005184", "30005176", "30005164"],
        )
        self.assertEqual(
            result.notices[0]["detail_url"],
            (
                "https://recruit.navercorp.com/rcrt/view.do"
                "?annoId=30005184&lang=ko"
            ),
        )
        self.assertEqual(result.notices[0]["published_at"], "2026-07-21")

    def test_split_cell_list_rows_are_extracted_as_records(self):
        html = """
        <div class="table-style">
          <div class="tb-body">
            <ul class="clearfix on">
              <li>[공지]</li>
              <li><a href="#a" onclick="fnView('1', '16197')">
                2026-2학기 수강신청 안내
              </a></li>
              <li>컴퓨터과학부</li>
              <li>2026-07-23</li>
            </ul>
            <ul class="clearfix on">
              <li>[공지]</li>
              <li><a href="#a" onclick="fnView('2', '16187')">
                장바구니 수강신청 실시 안내
              </a></li>
              <li>컴퓨터과학부</li>
              <li>2026-07-15</li>
            </ul>
            <ul class="clearfix on">
              <li>[공지]</li>
              <li><a href="#a" onclick="fnView('3', '15975')">
                공결 신청 안내
              </a></li>
              <li>컴퓨터과학부</li>
              <li>2026-03-17</li>
            </ul>
          </div>
        </div>
        """

        result = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url=(
                "https://engineering.uos.ac.kr/engineering/korNotice/"
                "allList.do?list_id=20013DA1&cate_id2=000010383"
                "&identified=anonymous"
            ),
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.notices), 3)
        self.assertEqual(
            [notice["external_id"] for notice in result.notices],
            ["16197", "16187", "15975"],
        )
        self.assertEqual(
            result.notices[0]["detail_url"],
            (
                "https://engineering.uos.ac.kr/engineering/korNotice/"
                "view.do?list_id=20013DA1&seq=16197&sort=1"
                "&cate_id2=000010383&identified=anonymous"
            ),
        )


if __name__ == "__main__":
    unittest.main()
