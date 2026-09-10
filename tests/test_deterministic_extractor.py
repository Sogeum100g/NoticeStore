import json
import unittest
from pathlib import Path

from dataController.scraper.deterministic_extractor import (
    _normalize_date,
    _streaming_table_candidates,
    extract_notices_deterministically,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class DeterministicJsonExtractorTests(unittest.TestCase):
    def test_application_period_does_not_replace_published_date(self):
        result = extract_notices_deterministically(
            {
                "items": [
                    {
                        "id": "1",
                        "title": "사업 지원 공고",
                        "registeredAt": "2026-08-20",
                        "applicationStartDate": "2026-09-01",
                        "applicationEndDate": "2026-09-30",
                    },
                    {
                        "id": "2",
                        "title": "다른 사업 공고",
                        "registeredAt": "2026-08-21",
                        "applicationStartDate": "2026-09-02",
                        "applicationEndDate": "2026-10-01",
                    },
                ]
            },
            content_type="application/json",
            base_url="https://business.example/notices",
        )

        self.assertEqual(result.notices[0]["published_at"], "2026-08-20")
        self.assertEqual(
            result.extractor_config["date_roles"],
            {
                "published_at": "registeredAt",
                "application_start_at": "applicationStartDate",
                "application_end_at": "applicationEndDate",
            },
        )

    def test_hanwha_recruitment_fields_and_detail_urls_are_extracted(self):
        raw = json.loads(
            (FIXTURE_DIR / "hanwha_recruit.json").read_text(encoding="utf-8")
        )

        result = extract_notices_deterministically(
            raw,
            content_type="application/json",
            base_url="https://www.hanwhain.com/portal/apply/recruit",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.notices), 2)
        self.assertEqual(result.notices[0]["external_id"], "19483")
        self.assertEqual(result.notices[0]["author"], "(주)한화 글로벌부문")
        self.assertIsNone(result.notices[0]["published_at"])
        self.assertEqual(
            result.extractor_config["date_roles"]["application_start_at"],
            "rtAcptStrtDttm",
        )
        self.assertEqual(
            result.extractor_config["date_roles"]["application_end_at"],
            "rtAcptEndDttm",
        )
        self.assertEqual(
            result.notices[0]["detail_url"],
            (
                "https://www.hanwhain.com/portal/apply/recruit/detail"
                "?rtSeq=19483"
            ),
        )

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
                "?company=KAKAO&page=1&part=TECHNOLOGY"
            ),
        )


class DeterministicHtmlExtractorTests(unittest.TestCase):
    def test_event_schedule_is_not_published_date(self):
        html = """
        <section class="event_main_area"><ul class="event_lists">
          <li><a href="/event/1"><h3>첫 행사</h3>
              <span class="date">2026.09.19</span></a></li>
          <li><a href="/event/2"><h3>둘째 행사</h3>
              <span class="date">2026.09.20</span></a></li>
        </ul></section>
        """
        result = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url="https://events.example/event/main",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.notices), 2)
        self.assertTrue(
            all(notice["published_at"] is None for notice in result.notices)
        )

    def test_identical_sibling_list_parents_keep_selected_region(self):
        html = """
        <div class="notice-list">
          <ul>
            <li class="pinned"><a href="/1">고정 1</a><time>2026-08-01</time></li>
            <li class="pinned"><a href="/2">고정 2</a><time>2026-08-02</time></li>
          </ul>
          <ul>
            <li><a href="/11">일반 1</a><time>2026-08-11</time></li>
            <li><a href="/12">일반 2</a><time>2026-08-12</time></li>
            <li><a href="/13">일반 3</a><time>2026-08-13</time></li>
          </ul>
        </div>
        """
        result = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url="https://example.com/notices",
        )

        self.assertEqual(len(result.notices), 3)
        self.assertIn(":nth-of-type(2)", result.extractor_config["record_css"])

    def test_recruitment_round_number_is_not_parsed_as_calendar_date(self):
        self.assertIsNone(_normalize_date("2026년 8월 6차 채용"))

    def test_pinned_rows_are_separated_from_general_notice_region(self):
        pinned_rows = "".join(
            f"""
            <tr class="pinned"><td><a href="/notice/p{index}">
            고정 공지 {index}</a></td><td>2026.08.{20 + index}</td></tr>
            """
            for index in range(2)
        )
        general_rows = "".join(
            f"""
            <tr><td><a href="/notice/{index}">일반 공지 {index}</a></td>
            <td>2026.08.{10 + index}</td></tr>
            """
            for index in range(4)
        )
        html = f"""
        <main id="board"><table><tbody>
          {pinned_rows}
          {general_rows}
        </tbody></table></main>
        """

        first = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url="https://public.example/notices",
        )
        recurring = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url="https://public.example/notices",
            extractor_config=first.extractor_config,
        )

        self.assertEqual(first.status, "success")
        self.assertEqual(len(first.notices), 4)
        self.assertTrue(
            all(notice["title"].startswith("일반") for notice in first.notices)
        )
        self.assertIn(":not(.pinned)", first.extractor_config["record_css"])
        self.assertEqual(
            [notice["title"] for notice in recurring.notices],
            [notice["title"] for notice in first.notices],
        )

    def test_table_rows_use_full_dates_from_title_attributes(self):
        html = (FIXTURE_DIR / "dcinside_board.html").read_text(
            encoding="utf-8"
        )

        result = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url="https://gall.dcinside.com/board/lists/?id=hair",
        )

        self.assertEqual(result.status, "success")
        self.assertIn(
            "tr.ub-content.us-post",
            result.extractor_config["record_css"],
        )
        self.assertEqual(len(result.notices), 3)
        self.assertEqual(result.notices[1]["external_id"], "652187")
        self.assertEqual(
            result.notices[1]["published_at"],
            "2026-08-25T18:17:37",
        )
        self.assertEqual(result.notices[1]["author"], "작성자1")

    def test_jobkorea_deadline_cards_are_extracted_instead_of_ui_articles(self):
        html = (FIXTURE_DIR / "jobkorea_recruit.html").read_text(
            encoding="utf-8"
        )

        result = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url="https://www.jobkorea.co.kr/company/1882711/recruit",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.notices), 3)
        self.assertNotEqual(result.extractor_config["record_css"], "article")
        self.assertEqual(
            [notice["title"] for notice in result.notices],
            [
                "[넥슨컴퍼니] 2026 넥토리얼 for Game Programmer",
                "중국 사업/마케팅 담당자",
                "개발 PM (기획 담당)",
            ],
        )
        self.assertEqual(result.notices[0]["external_id"], "49843485")
        self.assertEqual(
            result.notices[0]["detail_url"],
            (
                "https://www.jobkorea.co.kr/Recruit/GI_Read/49843485"
                "?Oem_Code=C1"
            ),
        )
        self.assertIsNone(result.notices[0]["published_at"])

    def test_v4_article_rule_is_rediscovered(self):
        html = (FIXTURE_DIR / "jobkorea_recruit.html").read_text(
            encoding="utf-8"
        )

        result = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url="https://www.jobkorea.co.kr/company/1882711/recruit",
            extractor_config={
                "version": 4,
                "source_type": "html",
                "record_css": "article",
            },
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.extractor_config["version"], 6)
        self.assertNotEqual(result.extractor_config["record_css"], "article")
        self.assertEqual(len(result.notices), 3)

    def test_english_text_dates_in_list_items_are_extracted(self):
        html = """
        <ul class="list-news">
          <li>
            <h2><a href="/weblog/2026/aug/24/first/">
              First Django announcement
            </a></h2>
            <span class="meta">
              Posted by <strong>Alice Example</strong> on Aug. 24, 2026
            </span>
          </li>
          <li>
            <h2><a href="/weblog/2026/aug/20/second/">
              Second Django announcement
            </a></h2>
            <span class="meta">
              Posted by <strong>Bob Example</strong> on Aug. 20, 2026
            </span>
          </li>
        </ul>
        """

        result = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url="https://www.djangoproject.com/weblog/",
        )

        self.assertEqual(result.status, "success")
        self.assertIn("ul.list-news > li", result.extractor_config["record_css"])
        self.assertEqual(len(result.notices), 2)
        self.assertEqual(result.notices[0]["published_at"], "2026-08-24")
        self.assertEqual(result.notices[0]["author"], "Alice Example")
        self.assertEqual(
            result.notices[0]["detail_url"],
            "https://www.djangoproject.com/weblog/2026/aug/24/first/",
        )

    def test_table_preparser_does_not_materialize_unrelated_dom(self):
        html = """
        <div class="global-navigation">대형 메뉴 DOM</div>
        <table><tbody>
          <tr><td><a href="/n/2">두 번째 공지사항 안내</a></td><td>2026.08.10</td></tr>
          <tr><td><a href="/n/1">첫 번째 공지사항 안내</a></td><td>2026.08.09</td></tr>
        </tbody></table>
        """
        soup, records = _streaming_table_candidates(html)
        try:
            self.assertEqual(len(records), 2)
            self.assertIsNone(soup.select_one(".global-navigation"))
        finally:
            soup.decompose()

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

    def test_two_digit_year_table_dates_are_normalized(self):
        html = """
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
        """
        result = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url="https://swuniv.cnu.ac.kr/swuniv/community/notice.do",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.notices), 2)
        self.assertEqual(result.notices[0]["published_at"], "2026-08-24")
        self.assertEqual(result.notices[0]["author"], "소프트웨어중심대학")
        self.assertEqual(
            result.notices[0]["detail_url"],
            (
                "https://swuniv.cnu.ac.kr/swuniv/community/notice.do"
                "?articleNo=595367&mode=view"
            ),
        )

    def test_numeric_view_count_is_not_inferred_as_author(self):
        html = """
        <table class="board">
          <tbody>
            <tr>
              <td>1304</td>
              <td><a href="?mode=view&amp;seqNo=21173">첫 번째 장학금 공지 안내</a></td>
              <td>2026.08.10</td>
              <td>16,547</td>
            </tr>
            <tr>
              <td>1303</td>
              <td><a href="?mode=view&amp;seqNo=21169">두 번째 장학금 공지 안내</a></td>
              <td>2026.08.07</td>
              <td>25,834</td>
            </tr>
          </tbody>
        </table>
        """
        result = extract_notices_deterministically(
            html,
            content_type="text/html",
            base_url="https://www.kosaf.go.kr/ko/notice.do",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.notices[0]["author"], "")

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
        self.assertEqual(result.extractor_config["version"], 6)
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
        self.assertEqual(result.extractor_config["version"], 6)
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
        self.assertIsNone(result.notices[0]["published_at"])

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
        self.assertIsNone(result.notices[0]["published_at"])

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
                "view.do?cate_id2=000010383&identified=anonymous"
                "&list_id=20013DA1&seq=16197&sort=1"
            ),
        )


if __name__ == "__main__":
    unittest.main()
