import unittest

from dataController.scraper.declarative_rule_executor import (
    RuleExecutionEvidence,
    RuleExecutionResult,
    execute_extractor_rule,
)
from dataController.scraper.extraction_agent_contracts import ExtractorRuleV1
from dataController.scraper.rule_hard_gate import (
    build_result_evaluation_request,
    validate_rule_execution,
)


def html_rule() -> ExtractorRuleV1:
    return ExtractorRuleV1.model_validate(
        {
            "version": 1,
            "source_type": "html",
            "record_selector": "article.notice",
            "records_path": None,
            "fields": {
                "title": {
                    "kind": "html",
                    "selector": "h2",
                    "source": "text",
                    "attribute": None,
                    "transforms": ["normalize_space"],
                },
                "published_at": {
                    "kind": "html",
                    "selector": "time",
                    "source": "attribute",
                    "attribute": "datetime",
                    "transforms": ["date"],
                },
                "detail_url": {
                    "kind": "html",
                    "selector": "a",
                    "source": "attribute",
                    "attribute": "href",
                    "transforms": ["urljoin"],
                },
            },
            "evidence_ids": ["html-group-0"],
        }
    )


def evidence(index: int) -> RuleExecutionEvidence:
    return RuleExecutionEvidence(
        record_index=index,
        evidence_id=f"executed-record-{index}",
        source_type="html",
        record_tag="article",
        record_attributes={"class": "notice"},
        visible_text=f"공지 {index} 보기",
        field_values={
            "title": f"공지 {index}",
            "published_at": "2026-08-25",
            "detail_url": f"/notice/{index}",
        },
    )


class RuleHardGateTests(unittest.TestCase):
    def test_html_execution_evidence_removes_svg_and_keeps_field_structure(self):
        raw_html = """
        <main>
          <article class="notice card" onclick="track()">
            <svg viewBox="0 0 10 10"><path d="%s"></path></svg>
            <script>track-secret()</script>
            <h2>첫 번째 공지</h2>
            <time datetime="2026-08-25">2026.08.25</time>
            <a href="/notice/1">자세히 보기</a>
          </article>
        </main>
        """ % ("M0 0 " * 1000)

        execution = execute_extractor_rule(
            raw_html,
            rule=html_rule(),
            base_url="https://example.com/notices",
        )

        self.assertEqual(execution.status, "success")
        self.assertEqual(len(execution.evidence), 1)
        source = execution.evidence[0]
        self.assertEqual(source.record_tag, "article")
        self.assertEqual(source.record_attributes, {"class": "notice card"})
        self.assertEqual(source.visible_text, "첫 번째 공지 2026.08.25 자세히 보기")
        self.assertNotIn("M0 0", source.visible_text)
        self.assertEqual(source.field_values["title"], "첫 번째 공지")
        self.assertEqual(source.field_values["published_at"], "2026-08-25")
        self.assertEqual(source.field_values["detail_url"], "/notice/1")

    def test_valid_execution_builds_result_evaluation_request(self):
        execution = RuleExecutionResult(
            status="success",
            source_record_count=3,
            notices=[
                {
                    "title": f"공지 {index}",
                    "author": None,
                    "published_at": "2026-08-25",
                    "detail_url": f"https://example.com/notice/{index}",
                    "external_id": str(index),
                }
                for index in range(3)
            ],
            evidence=[evidence(index) for index in range(3)],
            rejected_evidence=[],
            rejected_record_count=0,
        )

        gate = validate_rule_execution(
            execution,
            rule=html_rule(),
            semantic_record_count=3,
        )
        request = build_result_evaluation_request(
            target_url="https://example.com/notices",
            source_url="https://example.com/notices",
            rule=html_rule(),
            execution=execution,
            hard_gate=gate,
        )

        self.assertTrue(gate.passed)
        self.assertEqual(gate.metrics.coverage_ratio, 1.0)
        self.assertEqual(len(request.samples), 3)
        self.assertEqual(request.version, 2)
        self.assertEqual(
            request.samples[0].source.evidence_id,
            "executed-record-0",
        )
        self.assertEqual(request.samples[0].source.field_values.title, "공지 0")

    def test_evaluator_v2_uses_six_diverse_structured_samples(self):
        notices = [
            {
                "title": "매우 긴 제목 " + ("가" * 80) if index == 7 else f"공지 {index}",
                "author": None,
                "published_at": "2026-08-25",
                "detail_url": f"https://example.com/notice/{index}",
                "external_id": str(index),
            }
            for index in range(20)
        ]
        execution = RuleExecutionResult(
            status="success",
            source_record_count=20,
            notices=notices,
            evidence=[evidence(index) for index in range(20)],
            rejected_evidence=[],
            rejected_record_count=0,
        )
        gate = validate_rule_execution(
            execution,
            rule=html_rule(),
            semantic_record_count=20,
        )

        request = build_result_evaluation_request(
            target_url="https://example.com/notices",
            source_url="https://example.com/notices",
            rule=html_rule(),
            execution=execution,
            hard_gate=gate,
        )

        self.assertEqual(len(request.samples), 6)
        indices = [sample.source.record_index for sample in request.samples]
        self.assertIn(0, indices)
        self.assertIn(19, indices)
        self.assertIn(10, indices)
        self.assertIn(7, indices)
        payload = request.model_dump(mode="json", exclude_none=True)
        self.assertNotIn("source_excerpt", str(payload))
        self.assertIn("field_values", payload["samples"][0]["source"])

    def test_large_coverage_drop_is_sent_to_semantic_evaluator(self):
        execution = RuleExecutionResult(
            status="success",
            source_record_count=10,
            notices=[
                {
                    "title": "한 건만 잘못 추출",
                    "author": None,
                    "published_at": "2026-08-25",
                    "detail_url": "https://example.com/notice/1",
                    "external_id": "1",
                }
            ],
            evidence=[evidence(0)],
            rejected_evidence=[],
            rejected_record_count=0,
        )

        gate = validate_rule_execution(
            execution,
            rule=html_rule(),
            semantic_record_count=10,
        )

        self.assertTrue(gate.passed)
        self.assertNotIn("COVERAGE_MISMATCH", gate.reason_codes)
        self.assertIn(
            "COVERAGE_MISMATCH",
            gate.semantic_diagnostic_codes,
        )
        request = build_result_evaluation_request(
            target_url="https://example.com/notices",
            source_url="https://example.com/notices",
            rule=html_rule(),
            execution=execution,
            hard_gate=gate,
        )
        self.assertEqual(
            request.semantic_diagnostic_codes,
            ["COVERAGE_MISMATCH"],
        )

    def test_scoped_deterministic_baseline_overrides_page_wide_count(self):
        baseline_notices = [
            {
                "title": f"공지 {index}",
                "author": None,
                "published_at": "2026-09-09",
                "detail_url": f"https://example.com/notice/{index}",
                "external_id": str(index),
            }
            for index in range(10)
        ]
        execution = RuleExecutionResult(
            status="success",
            source_record_count=10,
            notices=[dict(notice) for notice in baseline_notices],
            evidence=[evidence(index) for index in range(10)],
            rejected_evidence=[],
            rejected_record_count=0,
        )

        gate = validate_rule_execution(
            execution,
            rule=html_rule(),
            # A page-wide analyzer also counted an unrelated event banner.
            semantic_record_count=25,
            baseline_notices=baseline_notices,
        )

        self.assertTrue(gate.passed)
        self.assertEqual(gate.metrics.coverage_ratio, 1.0)
        self.assertEqual(gate.metrics.semantic_record_count, 25)
        self.assertEqual(gate.metrics.baseline_record_count, 10)
        self.assertEqual(gate.metrics.reference_record_count, 10)
        self.assertIn(
            "COVERAGE_MISMATCH",
            gate.semantic_diagnostic_codes,
        )

    def test_large_over_extraction_is_sent_to_semantic_evaluator(self):
        execution = RuleExecutionResult(
            status="success",
            source_record_count=7,
            notices=[
                {
                    "title": f"공지 {index}",
                    "author": None,
                    "published_at": "2026-08-25",
                    "detail_url": f"https://example.com/notice/{index}",
                    "external_id": str(index),
                }
                for index in range(7)
            ],
            evidence=[evidence(index) for index in range(7)],
            rejected_evidence=[],
            rejected_record_count=0,
        )

        gate = validate_rule_execution(
            execution,
            rule=html_rule(),
            semantic_record_count=5,
        )

        self.assertTrue(gate.passed)
        self.assertNotIn("OVER_EXTRACTION", gate.reason_codes)
        self.assertIn("OVER_EXTRACTION", gate.semantic_diagnostic_codes)

    def test_configured_invalid_urls_and_dates_fail(self):
        execution = RuleExecutionResult(
            status="success",
            source_record_count=2,
            notices=[
                {
                    "title": "첫 번째 공지",
                    "author": None,
                    "published_at": None,
                    "detail_url": None,
                    "external_id": "1",
                },
                {
                    "title": "두 번째 공지",
                    "author": None,
                    "published_at": None,
                    "detail_url": "javascript:open(2)",
                    "external_id": "2",
                },
            ],
            evidence=[evidence(0), evidence(1)],
            rejected_evidence=[],
            rejected_record_count=0,
        )

        gate = validate_rule_execution(execution, rule=html_rule())

        self.assertFalse(gate.passed)
        self.assertIn("INVALID_DETAIL_URLS", gate.reason_codes)
        self.assertIn("INVALID_DATES", gate.reason_codes)

    def test_candidate_cannot_drop_baseline_detail_urls(self):
        baseline_notices = [
            {
                "title": f"공지 {index}",
                "author": None,
                "published_at": None,
                "detail_url": f"https://example.com/notice/{index}",
                "external_id": str(index),
            }
            for index in range(4)
        ]
        execution = RuleExecutionResult(
            status="success",
            source_record_count=4,
            notices=[
                {
                    "title": f"공지 {index}",
                    "author": None,
                    "published_at": None,
                    "detail_url": None,
                    "external_id": str(index),
                }
                for index in range(4)
            ],
            evidence=[evidence(index) for index in range(4)],
            rejected_evidence=[],
            rejected_record_count=0,
        )

        gate = validate_rule_execution(
            execution,
            rule=ExtractorRuleV1.model_validate(
                {
                    "version": 1,
                    "source_type": "html",
                    "record_selector": "article.notice",
                    "fields": {
                        "title": {
                            "kind": "html",
                            "selector": "h2",
                            "source": "text",
                        },
                        "external_id": {
                            "kind": "html",
                            "selector": ":scope",
                            "source": "attribute",
                            "attribute": "data-id",
                        },
                    },
                    "evidence_ids": ["html-group-0"],
                }
            ),
            baseline_notices=baseline_notices,
        )

        self.assertFalse(gate.passed)
        self.assertIn(
            "FIELD_COVERAGE_REGRESSION_DETAIL_URL",
            gate.reason_codes,
        )

    def test_duplicate_identity_fails(self):
        duplicate_notice = {
            "title": "중복 공지",
            "author": None,
            "published_at": "2026-08-25",
            "detail_url": "https://example.com/notice/1",
            "external_id": "1",
        }
        execution = RuleExecutionResult(
            status="success",
            source_record_count=3,
            notices=[dict(duplicate_notice) for _ in range(3)],
            evidence=[evidence(index) for index in range(3)],
            rejected_evidence=[],
            rejected_record_count=0,
        )

        gate = validate_rule_execution(execution, rule=html_rule())

        self.assertFalse(gate.passed)
        self.assertEqual(gate.metrics.duplicate_record_count, 2)
        self.assertIn("DUPLICATE_RECORDS", gate.reason_codes)


if __name__ == "__main__":
    unittest.main()
