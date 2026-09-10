import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from dataController.scraper.extraction_agent_contracts import (
    ExtractorRuleV1,
    ResultEvaluationV1,
    ResultEvaluationV2,
    SourceViewCandidateV1,
    SourceViewSelectionRequestV1,
    SourceViewSelectionV1,
    extractor_rule_json_schema,
    result_evaluation_json_schema,
)
from dataController.scraper.declarative_rule_executor import (
    execute_extractor_rule,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class ExtractorRuleContractTests(unittest.TestCase):
    def test_view_selection_contract_rejects_low_confidence_and_duplicates(self):
        candidate = SourceViewCandidateV1(
            strategy="navigation_preserving",
            payload_hash="a" * 64,
            validation_state="READY",
            reason_codes=[],
            evidence_loss={"navigation": 0.0},
            payload_chars=100,
            truncated=False,
            groups=[],
        )
        with self.assertRaises(ValidationError):
            SourceViewSelectionRequestV1(
                version=1,
                candidates=[candidate, candidate],
            )
        with self.assertRaises(ValidationError):
            SourceViewSelectionV1(
                version=1,
                strategy="navigation_preserving",
                payload_hash="a" * 64,
                confidence=0.79,
                reason="불확실",
            )

    def test_accepts_allowlisted_html_rule(self):
        rule = ExtractorRuleV1.model_validate(
            {
                "version": 1,
                "source_type": "html",
                "record_selector": "table tbody tr.ub-content",
                "records_path": None,
                "fields": {
                    "title": {
                        "kind": "html",
                        "selector": "td.gall_tit a",
                        "source": "text",
                        "attribute": None,
                        "transforms": ["strip", "normalize_space"],
                    },
                    "published_at": {
                        "kind": "html",
                        "selector": "td.gall_date",
                        "source": "attribute",
                        "attribute": "title",
                        "transforms": ["date"],
                    },
                    "detail_url": {
                        "kind": "html",
                        "selector": "td.gall_tit a",
                        "source": "attribute",
                        "attribute": "href",
                        "transforms": ["urljoin"],
                    },
                    "external_id": {
                        "kind": "html",
                        "selector": ":scope",
                        "source": "attribute",
                        "attribute": "data-no",
                        "transforms": ["strip"],
                    },
                },
                "evidence_ids": ["record-group-1", "field-date-1"],
            }
        )

        self.assertEqual(rule.source_type, "html")
        self.assertEqual(rule.fields.published_at.attribute, "title")

    def test_rejects_generated_wrapper_id_but_keeps_stable_numeric_id(self):
        base_rule = {
            "version": 1,
            "source_type": "html",
            "record_selector": "#notice1 > li",
            "fields": {
                "title": {
                    "kind": "html",
                    "selector": "a.title",
                    "source": "text",
                    "transforms": ["normalize_space"],
                }
            },
            "evidence_ids": ["record-group-1"],
        }
        accepted = ExtractorRuleV1.model_validate(base_rule)
        self.assertEqual(accepted.record_selector, "#notice1 > li")

        with self.assertRaisesRegex(
            ValidationError,
            "동적 HTML ID",
        ):
            ExtractorRuleV1.model_validate(
                {
                    **base_rule,
                    "record_selector": (
                        "#dpt-wrapper-802 > div.dpt-entry.has-thumbnail"
                    ),
                }
            )

    def test_rejects_executable_or_event_attribute(self):
        with self.assertRaises(ValidationError):
            ExtractorRuleV1.model_validate(
                {
                    "version": 1,
                    "source_type": "html",
                    "record_selector": "article.notice",
                    "records_path": None,
                    "fields": {
                        "title": {
                            "kind": "html",
                            "selector": "a",
                            "source": "attribute",
                            "attribute": "onclick",
                            "transforms": [],
                        }
                    },
                    "evidence_ids": ["record-group-1"],
                }
            )

    def test_accepts_navigation_source_for_detail_url_only(self):
        rule = ExtractorRuleV1.model_validate(
            {
                "version": 1,
                "source_type": "html",
                "record_selector": "article.notice",
                "fields": {
                    "title": {
                        "kind": "html",
                        "selector": "a.title",
                        "source": "text",
                        "transforms": ["normalize_space"],
                    },
                    "detail_url": {
                        "kind": "html",
                        "selector": "a.title",
                        "source": "navigation",
                        "transforms": [],
                    },
                },
                "evidence_ids": ["record-group-1"],
            }
        )
        self.assertEqual(rule.fields.detail_url.source, "navigation")

        with self.assertRaises(ValidationError):
            ExtractorRuleV1.model_validate(
                {
                    "version": 1,
                    "source_type": "html",
                    "record_selector": "article.notice",
                    "fields": {
                        "title": {
                            "kind": "html",
                            "selector": "a.title",
                            "source": "navigation",
                            "transforms": [],
                        }
                    },
                    "evidence_ids": ["record-group-1"],
                }
            )

    def test_rejects_mixed_source_field_rules(self):
        with self.assertRaises(ValidationError):
            ExtractorRuleV1.model_validate(
                {
                    "version": 1,
                    "source_type": "html",
                    "record_selector": "article.notice",
                    "records_path": None,
                    "fields": {
                        "title": {
                            "kind": "json",
                            "path": "$.title",
                            "transforms": ["strip"],
                        }
                    },
                    "evidence_ids": ["record-group-1"],
                }
            )

    def test_accepts_simple_json_paths(self):
        rule = ExtractorRuleV1.model_validate(
            {
                "version": 1,
                "source_type": "json",
                "record_selector": None,
                "records_path": "$.data.list",
                "fields": {
                    "title": {
                        "kind": "json",
                        "path": "$.rtNm",
                        "transforms": ["strip"],
                    },
                    "author": {
                        "kind": "json",
                        "path": "$.sdNm",
                        "transforms": ["strip"],
                    },
                    "published_at": {
                        "kind": "json",
                        "path": "$.publishedAt",
                        "transforms": ["date"],
                    },
                    "external_id": {
                        "kind": "json",
                        "path": "$.rtSeq",
                        "transforms": ["strip"],
                    },
                },
                "evidence_ids": ["json-array-1"],
            }
        )

        self.assertEqual(rule.records_path, "$.data.list")
        self.assertEqual(rule.fields.title.path, "$.rtNm")

    def test_accepts_and_executes_json_detail_url_template(self):
        rule = ExtractorRuleV1.model_validate(
            {
                "version": 1,
                "source_type": "json",
                "records_path": "$.jobList",
                "fields": {
                    "title": {
                        "kind": "json",
                        "path": "$.jobOfferTitle",
                        "transforms": ["normalize_space"],
                    },
                    "detail_url": {
                        "kind": "json",
                        "template": (
                            "https://careers.example/jobs/{external_id}"
                        ),
                        "template_fields": {"external_id": "$.realId"},
                        "transforms": [],
                    },
                },
                "evidence_ids": ["json-array-1"],
            }
        )

        result = execute_extractor_rule(
            {
                "jobList": [
                    {"realId": "P/14472", "jobOfferTitle": "AI Engineer"}
                ]
            },
            rule=rule,
            base_url="https://careers.example/jobs",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.notices[0]["detail_url"],
            "https://careers.example/jobs/P%2F14472",
        )

    def test_rejects_json_template_placeholder_mismatch(self):
        with self.assertRaises(ValidationError):
            ExtractorRuleV1.model_validate(
                {
                    "version": 1,
                    "source_type": "json",
                    "records_path": "$.items",
                    "fields": {
                        "title": {"kind": "json", "path": "$.title"},
                        "detail_url": {
                            "kind": "json",
                            "template": "https://example.test/{id}",
                            "template_fields": {"external_id": "$.id"},
                        },
                    },
                    "evidence_ids": ["json-array-1"],
                }
            )

    def test_rejects_application_period_as_published_date(self):
        with self.assertRaises(ValidationError):
            ExtractorRuleV1.model_validate(
                {
                    "version": 1,
                    "source_type": "json",
                    "records_path": "$.items",
                    "fields": {
                        "title": {"kind": "json", "path": "$.title"},
                        "published_at": {
                            "kind": "json",
                            "path": "$.applicationStartDate",
                            "transforms": ["date"],
                        },
                    },
                    "evidence_ids": ["json-array-1"],
                }
            )

    def test_contracts_forbid_unknown_properties(self):
        with self.assertRaises(ValidationError):
            ExtractorRuleV1.model_validate(
                {
                    "version": 1,
                    "source_type": "json",
                    "record_selector": None,
                    "records_path": "$.list",
                    "fields": {
                        "title": {
                            "kind": "json",
                            "path": "$.title",
                            "transforms": [],
                            "python": "import os",
                        }
                    },
                    "evidence_ids": ["json-array-1"],
                }
            )

    def test_json_schemas_are_exportable_for_structured_outputs(self):
        rule_schema = extractor_rule_json_schema()
        evaluation_schema = result_evaluation_json_schema()

        self.assertEqual(rule_schema["additionalProperties"], False)
        self.assertEqual(evaluation_schema["additionalProperties"], False)
        self.assertIn("fields", rule_schema["properties"])
        self.assertIn("decision", evaluation_schema["properties"])


class ResultEvaluationContractTests(unittest.TestCase):
    def test_v2_output_version_matches_v2_request_contract(self):
        result = ResultEvaluationV2.model_validate(
            {
                "version": 2,
                "decision": "pass",
                "confidence": 0.96,
                "reason_codes": [],
                "affected_fields": [],
                "reason": "구조화된 필드 evidence와 결과가 일치합니다.",
            }
        )

        self.assertEqual(result.version, 2)
        with self.assertRaises(ValidationError):
            ResultEvaluationV2.model_validate(
                {
                    "version": 1,
                    "decision": "pass",
                    "confidence": 0.96,
                    "reason_codes": [],
                    "affected_fields": [],
                    "reason": "잘못된 계약 버전입니다.",
                }
            )

    def test_pass_requires_no_failure_codes(self):
        result = ResultEvaluationV1.model_validate(
            {
                "version": 1,
                "decision": "pass",
                "confidence": 0.96,
                "reason_codes": [],
                "affected_fields": [],
                "reason": "공지 레코드와 원본 근거가 일치합니다.",
            }
        )

        self.assertEqual(result.decision, "pass")

        with self.assertRaises(ValidationError):
            ResultEvaluationV1.model_validate(
                {
                    "version": 1,
                    "decision": "pass",
                    "confidence": 0.5,
                    "reason_codes": ["INSUFFICIENT_EVIDENCE"],
                    "affected_fields": [],
                    "reason": "근거가 부족하지만 통과합니다.",
                }
            )

        with self.assertRaises(ValidationError):
            ResultEvaluationV1.model_validate(
                {
                    "version": 1,
                    "decision": "pass",
                    "confidence": 0.79,
                    "reason_codes": [],
                    "affected_fields": [],
                    "reason": "신뢰도가 낮은 통과입니다.",
                }
            )

    def test_fail_is_closed_and_requires_reason_code(self):
        result = ResultEvaluationV1.model_validate(
            {
                "version": 1,
                "decision": "fail",
                "confidence": 0.91,
                "reason_codes": ["WRONG_CONTENT_REGION"],
                "affected_fields": ["title", "detail_url"],
                "reason": "공지 목록이 아니라 추천 콘텐츠 영역입니다.",
            }
        )

        self.assertEqual(result.decision, "fail")

        with self.assertRaises(ValidationError):
            ResultEvaluationV1.model_validate(
                {
                    "version": 1,
                    "decision": "fail",
                    "confidence": 0.5,
                    "reason_codes": [],
                    "affected_fields": [],
                    "reason": "판단할 수 없습니다.",
                }
            )


class DeclarativeRuleExecutorTests(unittest.TestCase):
    def test_text_rule_can_exclude_nested_badge_content(self):
        html = (FIXTURE_DIR / "jobkorea_recruit.html").read_text(
            encoding="utf-8"
        )
        rule = ExtractorRuleV1.model_validate(
            {
                "version": 1,
                "source_type": "html",
                "record_selector": "div.AgiCntnts",
                "fields": {
                    "title": {
                        "kind": "html",
                        "selector": "dt.tit",
                        "source": "text",
                        "exclude_selectors": ["em.iconNew"],
                        "transforms": ["normalize_space"],
                    },
                    "detail_url": {
                        "kind": "html",
                        "selector": "a.AgiLink",
                        "source": "attribute",
                        "attribute": "href",
                        "transforms": ["urljoin"],
                    },
                },
                "evidence_ids": ["jobkorea-record-group"],
            }
        )

        result = execute_extractor_rule(
            html,
            rule=rule,
            base_url="https://www.jobkorea.co.kr/company/1882711/recruit",
        )

        self.assertEqual(
            result.notices[0]["title"],
            "[넥슨컴퍼니] 2026 넥토리얼 for Game Programmer",
        )

    def test_executes_dcinside_dom_rule_without_site_aliases(self):
        html = (FIXTURE_DIR / "dcinside_board.html").read_text(encoding="utf-8")
        rule = ExtractorRuleV1.model_validate(
            {
                "version": 1,
                "source_type": "html",
                "record_selector": "tr.ub-content.us-post",
                "records_path": None,
                "fields": {
                    "title": {
                        "kind": "html",
                        "selector": "td.gall_tit a",
                        "source": "text",
                        "attribute": None,
                        "transforms": ["normalize_space"],
                    },
                    "author": {
                        "kind": "html",
                        "selector": "td.gall_writer",
                        "source": "text",
                        "attribute": None,
                        "transforms": ["normalize_space"],
                    },
                    "published_at": {
                        "kind": "html",
                        "selector": "td.gall_date",
                        "source": "attribute",
                        "attribute": "title",
                        "transforms": ["date"],
                    },
                    "detail_url": {
                        "kind": "html",
                        "selector": "td.gall_tit a",
                        "source": "attribute",
                        "attribute": "href",
                        "transforms": ["urljoin"],
                    },
                    "external_id": {
                        "kind": "html",
                        "selector": ":scope",
                        "source": "attribute",
                        "attribute": "data-no",
                        "transforms": ["strip"],
                    },
                },
                "evidence_ids": ["dcinside-record-group"],
            }
        )

        result = execute_extractor_rule(
            html,
            rule=rule,
            base_url="https://gall.dcinside.com/board/lists/?id=hair",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.source_record_count, 3)
        self.assertEqual(len(result.notices), 3)
        self.assertEqual(result.notices[1]["external_id"], "652187")
        self.assertEqual(
            result.notices[1]["published_at"],
            "2026-08-25T18:17:37",
        )
        self.assertEqual(
            result.notices[1]["detail_url"],
            "https://gall.dcinside.com/board/view/?id=hair&no=652187&page=1",
        )

    def test_executes_hanwha_json_rule_without_global_field_aliases(self):
        raw = json.loads(
            (FIXTURE_DIR / "hanwha_recruit.json").read_text(encoding="utf-8")
        )
        rule = ExtractorRuleV1.model_validate(
            {
                "version": 1,
                "source_type": "json",
                "record_selector": None,
                "records_path": "$.data.list",
                "fields": {
                    "title": {
                        "kind": "json",
                        "path": "$.rtNm",
                        "transforms": ["normalize_space"],
                    },
                    "author": {
                        "kind": "json",
                        "path": "$.sdNm",
                        "transforms": ["normalize_space"],
                    },
                    "external_id": {
                        "kind": "json",
                        "path": "$.rtSeq",
                        "transforms": ["strip"],
                    },
                },
                "evidence_ids": ["hanwha-record-array"],
            }
        )

        result = execute_extractor_rule(
            raw,
            rule=rule,
            base_url="https://www.hanwhain.com/portal/apply/recruit",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.source_record_count, 2)
        self.assertEqual(len(result.notices), 2)
        self.assertEqual(result.notices[0]["external_id"], "19483")
        self.assertIsNone(result.notices[0]["published_at"])
        self.assertEqual(result.notices[0]["author"], "(주)한화 글로벌부문")

if __name__ == "__main__":
    unittest.main()
