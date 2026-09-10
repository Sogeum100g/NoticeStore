import json
import unittest
from pathlib import Path

from dataController.scraper.extraction_shadow import compare_rule_based_shadow


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class ExtractionShadowTests(unittest.TestCase):
    def test_jobkorea_ui_false_positives_are_absent(self):
        raw = (FIXTURE_DIR / "jobkorea_recruit.html").read_text(encoding="utf-8")
        result = compare_rule_based_shadow(
            raw,
            content_type="text/html",
            base_url="https://www.jobkorea.co.kr/company/1882711/recruit",
            semantic_record_count=3,
            expected_titles=[
                "[넥슨컴퍼니] 2026 넥토리얼 for Game Programmer",
                "중국 사업/마케팅 담당자",
                "개발 PM (기획 담당)",
            ],
            prohibited_titles=[
                "리스트 정렬 순서 선택",
                "채용 진행 중 직무",
                "진행중인 채용정보",
            ],
        )

        self.assertEqual(result.status, "rule_based_pass")
        self.assertEqual(result.prohibited_title_hits, [])
        self.assertEqual(result.title_parity_ratio, 1.0)

    def test_dcinside_unsafe_generic_rule_requests_extractor(self):
        raw = (FIXTURE_DIR / "dcinside_board.html").read_text(encoding="utf-8")
        result = compare_rule_based_shadow(
            raw,
            content_type="text/html",
            base_url="https://gall.dcinside.com/board/lists/?id=hair",
            semantic_record_count=3,
        )

        self.assertEqual(result.status, "rule_extractor_required")
        self.assertFalse(result.hard_gate_passed)
        self.assertTrue(result.hard_gate_reason_codes)

    def test_hanwha_json_preserves_derived_detail_urls(self):
        raw = json.loads(
            (FIXTURE_DIR / "hanwha_recruit.json").read_text(encoding="utf-8")
        )
        result = compare_rule_based_shadow(
            raw,
            content_type="application/json",
            base_url="https://www.hanwhain.com/portal/apply/recruit",
            semantic_record_count=2,
        )

        self.assertEqual(result.status, "rule_based_pass")
        self.assertEqual(result.title_parity_ratio, 1.0)
        self.assertNotIn("detail_url", result.field_mismatches)

    def test_shadow_module_has_no_persistence_dependency(self):
        source = Path(
            __import__(
                "dataController.scraper.extraction_shadow",
                fromlist=["__file__"],
            ).__file__
        ).read_text(encoding="utf-8")

        self.assertNotIn("notice_repo", source)
        self.assertNotIn("activate_candidate_rule", source)


if __name__ == "__main__":
    unittest.main()
