import unittest
from unittest.mock import AsyncMock, patch

from dataController.scraper.extraction_agent_client import StructuredAgentResponse
from dataController.scraper.extraction_agent_contracts import (
    ExtractorRuleV1,
    ResultEvaluationV2,
    SourceViewSelectionV1,
)
from dataController.scraper.extraction_agent_orchestrator import (
    activate_candidate_rule,
)
from dataController.scraper.structure_sampler import (
    StructureSample,
    sample_source_structure as real_sample_source_structure,
)
from dataController.scraper.source_view_contracts import (
    SourceEvidenceProfile,
    SourceViewAttempt,
    SourceViewState,
    SourceViewValidation,
)


RAW_JSON = {
    "data": {
        "list": [
            {"title": "첫 번째 공지", "id": 1},
            {"title": "두 번째 공지", "id": 2},
        ]
    }
}


def json_rule(title_path: str = "$.title") -> ExtractorRuleV1:
    return ExtractorRuleV1.model_validate(
        {
            "version": 1,
            "source_type": "json",
            "record_selector": None,
            "records_path": "$.data.list",
            "fields": {
                "title": {
                    "kind": "json",
                    "path": title_path,
                    "transforms": ["normalize_space"],
                },
                "external_id": {
                    "kind": "json",
                    "path": "$.id",
                    "transforms": ["strip"],
                },
            },
            "evidence_ids": ["json-group-0"],
        }
    )


def html_navigation_rule() -> ExtractorRuleV1:
    return ExtractorRuleV1.model_validate(
        {
            "version": 1,
            "source_type": "html",
            "record_selector": "li.notice",
            "records_path": None,
            "fields": {
                "title": {
                    "kind": "html",
                    "selector": "a.detail",
                    "source": "text",
                    "transforms": ["normalize_space"],
                },
                "detail_url": {
                    "kind": "html",
                    "selector": "a.detail",
                    "source": "navigation",
                    "transforms": [],
                },
                "external_id": {
                    "kind": "html",
                    "selector": "a.detail",
                    "source": "onclick_literal",
                    "transforms": [],
                },
            },
            "evidence_ids": ["html-group-0"],
        }
    )


def evaluation(decision: str) -> ResultEvaluationV2:
    if decision == "pass":
        return ResultEvaluationV2(
            version=2,
            decision="pass",
            confidence=0.96,
            reason_codes=[],
            affected_fields=[],
            reason="실제 공지 목록과 일치합니다.",
        )
    return ResultEvaluationV2(
        version=2,
        decision="fail",
        confidence=0.92,
        reason_codes=["NON_NOTICE_CONTENT"],
        affected_fields=["title"],
        reason="공지 대신 추천 콘텐츠를 추출했습니다.",
    )


def rule_response(rule: ExtractorRuleV1) -> StructuredAgentResponse:
    return StructuredAgentResponse(
        stage="rule_extractor",
        value=rule,
        usage={"provider": "fixture", "input_tokens": 10, "output_tokens": 5},
    )


def evaluation_response(decision: str) -> StructuredAgentResponse:
    return StructuredAgentResponse(
        stage="result_evaluator",
        value=evaluation(decision),
        usage={"provider": "fixture", "input_tokens": 12, "output_tokens": 3},
    )


def source_view_attempt(
    strategy: str,
    payload_hash: str,
    *,
    ready: bool,
) -> SourceViewAttempt:
    raw = SourceEvidenceProfile(
        source_type="html",
        record_candidate_count=2,
        navigation_evidence_count=2,
        table_count=1,
    )
    if ready:
        validation = SourceViewValidation(
            state=SourceViewState.READY,
            reason_codes=[],
            evidence_loss={"records": 0.0, "navigation": 0.0},
        )
    else:
        validation = SourceViewValidation(
            state=SourceViewState.REPARSE_REQUIRED,
            reason_codes=[
                "RECORD_EVIDENCE_LOST",
                "NAVIGATION_EVIDENCE_LOST",
            ],
            evidence_loss={"records": 1.0, "navigation": 1.0},
        )
    return SourceViewAttempt(
        strategy=strategy,
        payload_hash=payload_hash,
        raw_evidence=raw,
        view_evidence=raw if ready else SourceEvidenceProfile(source_type="html"),
        validation=validation,
    )


class ExtractionAgentOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_view_selector_only_breaks_equal_quality_tie(self):
        samples = {
            strategy: StructureSample(
                source_type="html",
                payload={
                    "record_groups": [
                        {
                            "evidence_id": f"{strategy}-group",
                            "detected_record_count": 2,
                            "records": [{"html": "<tr><td>공지</td></tr>"}],
                        }
                    ],
                    "fallback_html": None,
                },
                evidence_ids={f"{strategy}-group"},
                truncated=False,
                strategy=strategy,
            )
            for strategy in (
                "default_structure_sampler",
                "navigation_preserving",
                "table_region_preserving",
            )
        }
        attempts = {
            "default_structure_sampler": source_view_attempt(
                "default_structure_sampler", "a" * 64, ready=False
            ),
            "navigation_preserving": source_view_attempt(
                "navigation_preserving", "b" * 64, ready=True
            ),
            "table_region_preserving": source_view_attempt(
                "table_region_preserving", "c" * 64, ready=True
            ),
        }
        selector = AsyncMock(
            return_value=StructuredAgentResponse(
                stage="view_selector",
                value=SourceViewSelectionV1(
                    version=1,
                    strategy="table_region_preserving",
                    payload_hash="c" * 64,
                    confidence=0.93,
                    reason="표 경계가 더 명확합니다.",
                ),
                usage={"provider": "fixture", "input_tokens": 8, "output_tokens": 2},
            )
        )
        generator = AsyncMock(side_effect=RuntimeError("invalid rule response"))
        with (
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "sample_source_structure",
                side_effect=lambda raw, source_type, strategy: samples[strategy],
            ),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "diagnose_source_view",
                side_effect=lambda raw, sample, source_type, strategy: attempts[
                    strategy
                ],
            ),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "select_source_view",
                new=selector,
            ),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "generate_extractor_rule",
                new=generator,
            ),
        ):
            result = await activate_candidate_rule(
                "<table></table>",
                source_type="html",
                target_url="https://example.com/notices",
                source_url="https://example.com/notices",
                semantic_record_count=2,
            )

        selector.assert_awaited_once()
        self.assertEqual(
            generator.await_args.kwargs["sample"].strategy,
            "table_region_preserving",
        )
        self.assertEqual(
            result.diagnostics["source_view_selection_mode"],
            "ai_tiebreak",
        )

    async def test_view_selector_failure_uses_stable_deterministic_fallback(self):
        samples = {
            strategy: StructureSample(
                "html",
                {
                    "record_groups": [
                        {
                            "evidence_id": f"{strategy}-group",
                            "detected_record_count": 2,
                            "records": [{"html": "<tr><td>공지</td></tr>"}],
                        }
                    ],
                    "fallback_html": None,
                },
                {f"{strategy}-group"},
                False,
                strategy,
            )
            for strategy in (
                "default_structure_sampler",
                "navigation_preserving",
                "table_region_preserving",
            )
        }
        attempts = {
            "default_structure_sampler": source_view_attempt(
                "default_structure_sampler", "a" * 64, ready=False
            ),
            "navigation_preserving": source_view_attempt(
                "navigation_preserving", "b" * 64, ready=True
            ),
            "table_region_preserving": source_view_attempt(
                "table_region_preserving", "c" * 64, ready=True
            ),
        }
        generator = AsyncMock(side_effect=RuntimeError("invalid rule response"))
        with (
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "sample_source_structure",
                side_effect=lambda raw, source_type, strategy: samples[strategy],
            ),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "diagnose_source_view",
                side_effect=lambda raw, sample, source_type, strategy: attempts[
                    strategy
                ],
            ),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "select_source_view",
                new=AsyncMock(side_effect=RuntimeError("selector unavailable")),
            ),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "generate_extractor_rule",
                new=generator,
            ),
        ):
            result = await activate_candidate_rule(
                "<table></table>",
                source_type="html",
                target_url="https://example.com/notices",
                source_url="https://example.com/notices",
                semantic_record_count=2,
            )

        self.assertEqual(
            generator.await_args.kwargs["sample"].strategy,
            "navigation_preserving",
        )
        self.assertEqual(
            result.diagnostics["source_view_selection_mode"],
            "deterministic_fallback",
        )

    async def test_failed_reparse_strategy_stops_before_rule_extractor(self):
        raw_html = """
        <ul class="notices">
          <li><a class="detail" href="javascript:goView('N-2')">둘째 공지</a></li>
          <li><a class="detail" href="javascript:goView('N-1')">첫째 공지</a></li>
        </ul>
        """

        def sampler(raw_data, *, source_type, strategy):
            if strategy == "navigation_preserving":
                raise RuntimeError("reparse unavailable")
            return real_sample_source_structure(
                raw_data,
                source_type=source_type,
                strategy=strategy,
            )

        generator = AsyncMock(side_effect=RuntimeError("invalid rule response"))
        with (
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "sample_source_structure",
                side_effect=sampler,
            ),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "generate_extractor_rule",
                new=generator,
            ),
        ):
            result = await activate_candidate_rule(
                raw_html,
                source_type="html",
                target_url="https://example.com/notices",
                source_url="https://example.com/notices",
                semantic_record_count=2,
            )

        generator.assert_not_awaited()
        self.assertEqual(result.failure_code, "VIEW_ATTEMPTS_EXHAUSTED")
        failed_stage = result.usage_by_stage[1]
        self.assertEqual(failed_stage["strategy"], "navigation_preserving")
        self.assertEqual(failed_stage["status"], "failed")
        self.assertEqual(result.diagnostics["recovery_state"], "REPARSE_REQUIRED")

    async def test_navigation_reparse_rule_can_pass_full_activation(self):
        raw_html = """
        <script>
          function goView(id) { window.location.href = '/notice/' + id; }
        </script>
        <ul class="notices">
          <li class="notice"><a class="detail" href="javascript:goView('N-2')"
                 onclick="return goView('N-2')">두 번째 공지</a></li>
          <li class="notice"><a class="detail" href="javascript:goView('N-1')"
                 onclick="return goView('N-1')">첫 번째 공지</a></li>
        </ul>
        """
        with (
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "generate_extractor_rule",
                new=AsyncMock(
                    return_value=rule_response(html_navigation_rule())
                ),
            ),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "evaluate_extraction_result",
                new=AsyncMock(return_value=evaluation_response("pass")),
            ),
        ):
            result = await activate_candidate_rule(
                raw_html,
                source_type="html",
                target_url="https://example.com/notices",
                source_url="https://example.com/notices",
                semantic_record_count=2,
            )

        self.assertTrue(result.approved)
        self.assertTrue(result.diagnostics["source_view_recovered"])
        self.assertEqual(
            [notice["detail_url"] for notice in result.approved_notices],
            [
                "https://example.com/notice/N-2",
                "https://example.com/notice/N-1",
            ],
        )

    async def test_navigation_loss_reparses_before_rule_generation(self):
        raw_html = """
        <ul class="notices">
          <li><a class="detail" href="javascript:goView('N-2')"
                 onclick="return goView('N-2')">두 번째 공지</a></li>
          <li><a class="detail" href="javascript:goView('N-1')"
                 onclick="return goView('N-1')">첫 번째 공지</a></li>
        </ul>
        """
        generator = AsyncMock(side_effect=RuntimeError("invalid rule response"))
        selector = AsyncMock()
        with (
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "generate_extractor_rule",
                new=generator,
            ),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "select_source_view",
                new=selector,
            ),
        ):
            result = await activate_candidate_rule(
                raw_html,
                source_type="html",
                target_url="https://example.com/notices",
                source_url="https://example.com/notices",
                semantic_record_count=2,
            )

        generated_sample = generator.await_args.kwargs["sample"]
        attempts = result.diagnostics["source_view_attempts"]
        sampler_stages = [
            stage
            for stage in result.usage_by_stage
            if stage["stage"] == "structure_sampler"
        ]
        self.assertEqual(
            [attempt["strategy"] for attempt in attempts],
            ["default_structure_sampler", "navigation_preserving"],
        )
        self.assertEqual(generated_sample.strategy, "navigation_preserving")
        selector.assert_not_awaited()
        self.assertTrue(result.diagnostics["source_view_recovered"])
        self.assertEqual(result.diagnostics["recovery_state"], "RULE_RETRY_REQUIRED")
        self.assertEqual([stage["selected"] for stage in sampler_stages], [False, True])

    async def test_missing_table_records_use_table_region_reparse(self):
        raw_html = """
        <table><tbody id="noticeRows">
          <tr><td>2</td><td class="subject">휴관 안내</td><td>2026-08-30</td></tr>
          <tr><td>1</td><td class="subject">운영시간 안내</td><td>2026-08-29</td></tr>
        </tbody></table>
        """
        generator = AsyncMock(side_effect=RuntimeError("invalid rule response"))
        with patch(
            "dataController.scraper.extraction_agent_orchestrator."
            "generate_extractor_rule",
            new=generator,
        ):
            result = await activate_candidate_rule(
                raw_html,
                source_type="html",
                target_url="https://example.com/notices",
                source_url="https://example.com/notices",
                semantic_record_count=2,
            )

        generated_sample = generator.await_args.kwargs["sample"]
        self.assertEqual(generated_sample.strategy, "table_region_preserving")
        self.assertEqual(
            [
                attempt["strategy"]
                for attempt in result.diagnostics["source_view_attempts"]
            ],
            ["default_structure_sampler", "table_region_preserving"],
        )
        self.assertTrue(result.diagnostics["source_view_recovered"])

    async def test_rule_generation_failure_preserves_rule_retry_diagnostics(self):
        with patch(
            "dataController.scraper.extraction_agent_orchestrator."
            "generate_extractor_rule",
            new=AsyncMock(side_effect=RuntimeError("invalid rule response")),
        ):
            result = await activate_candidate_rule(
                RAW_JSON,
                source_type="json",
                target_url="https://example.com/notices",
                source_url="https://example.com/notices.json",
                semantic_record_count=2,
            )

        self.assertEqual(result.failure_code, "RULE_GENERATION_FAILED")
        self.assertEqual(
            result.diagnostics["recovery_state"],
            "RULE_RETRY_REQUIRED",
        )
        self.assertEqual(
            result.diagnostics["source_view_attempt"]["strategy"],
            "default_structure_sampler",
        )

    async def test_truncated_source_view_preserves_reparse_diagnostics(self):
        truncated_sample = StructureSample(
            source_type="json",
            payload={
                "record_groups": [
                    {
                        "detected_record_count": 2,
                        "records": [
                            {"value": {"title": "첫 번째 공지", "id": 1}}
                        ],
                    }
                ],
                "fallback_json": None,
            },
            evidence_ids={"json-group-0"},
            truncated=True,
        )
        generator = AsyncMock(side_effect=RuntimeError("must not run"))
        with (
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "sample_source_structure",
                return_value=truncated_sample,
            ),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "generate_extractor_rule",
                new=generator,
            ),
        ):
            result = await activate_candidate_rule(
                RAW_JSON,
                source_type="json",
                target_url="https://example.com/notices",
                source_url="https://example.com/notices.json",
                semantic_record_count=2,
            )

        generator.assert_not_awaited()
        self.assertEqual(result.failure_code, "SOURCE_TRUNCATED")
        self.assertEqual(
            result.diagnostics["recovery_state"],
            "REPARSE_REQUIRED",
        )
        self.assertIn(
            "VIEW_TRUNCATED",
            result.diagnostics["source_view_attempt"]["validation"][
                "reason_codes"
            ],
        )

    async def test_unsupported_hydration_stops_before_rule_extractor(self):
        generator = AsyncMock(side_effect=RuntimeError("must not run"))
        with patch(
            "dataController.scraper.extraction_agent_orchestrator."
            "generate_extractor_rule",
            new=generator,
        ):
            result = await activate_candidate_rule(
                "<html><body><script>"
                "window.__STATE__ = buildState(fetch('/data'));"
                "</script></body></html>",
                source_type="html",
                target_url="https://example.com/notices",
                source_url="https://example.com/notices",
                semantic_record_count=2,
            )

        generator.assert_not_awaited()
        self.assertEqual(result.failure_code, "UNSUPPORTED_SOURCE_STRUCTURE")
        self.assertIn("Source View 준비 실패", result.reason)

    async def test_rule_based_success_skips_extractor_but_requires_evaluator(self):
        with (
            patch(
                "dataController.scraper.extraction_agent_orchestrator.generate_extractor_rule",
                new=AsyncMock(),
            ) as generate_mock,
            patch(
                "dataController.scraper.extraction_agent_orchestrator.evaluate_extraction_result",
                new=AsyncMock(return_value=evaluation_response("pass")),
            ) as evaluate_mock,
        ):
            result = await activate_candidate_rule(
                RAW_JSON,
                source_type="json",
                target_url="https://example.com/notices",
                source_url="https://example.com/notices.json",
                semantic_record_count=2,
                rule_based_candidate=json_rule(),
            )

        self.assertTrue(result.approved)
        self.assertEqual(result.rule_origin, "rule_based")
        self.assertEqual(len(result.approved_notices), 2)
        generate_mock.assert_not_awaited()
        evaluate_mock.assert_awaited_once()

    async def test_failed_rule_based_candidate_regenerates_once(self):
        with (
            patch(
                "dataController.scraper.extraction_agent_orchestrator.generate_extractor_rule",
                new=AsyncMock(return_value=rule_response(json_rule())),
            ) as generate_mock,
            patch(
                "dataController.scraper.extraction_agent_orchestrator.evaluate_extraction_result",
                new=AsyncMock(return_value=evaluation_response("pass")),
            ) as evaluate_mock,
        ):
            result = await activate_candidate_rule(
                RAW_JSON,
                source_type="json",
                target_url="https://example.com/notices",
                source_url="https://example.com/notices.json",
                semantic_record_count=2,
                rule_based_candidate=json_rule("$.missing"),
            )

        self.assertTrue(result.approved)
        self.assertEqual(result.rule_origin, "rule_extractor")
        generate_mock.assert_awaited_once()
        evaluate_mock.assert_awaited_once()
        self.assertEqual(
            [item["stage"] for item in result.usage_by_stage],
            ["structure_sampler", "rule_extractor", "result_evaluator"],
        )

    async def test_result_evaluator_fail_never_returns_approved_notices(self):
        with (
            patch(
                "dataController.scraper.extraction_agent_orchestrator.generate_extractor_rule",
                new=AsyncMock(return_value=rule_response(json_rule())),
            ) as generate_mock,
            patch(
                "dataController.scraper.extraction_agent_orchestrator.evaluate_extraction_result",
                new=AsyncMock(return_value=evaluation_response("fail")),
            ) as evaluate_mock,
        ):
            result = await activate_candidate_rule(
                RAW_JSON,
                source_type="json",
                target_url="https://example.com/notices",
                source_url="https://example.com/notices.json",
                semantic_record_count=2,
                rule_based_candidate=None,
            )

        self.assertFalse(result.approved)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.approved_notices, [])
        self.assertEqual(result.evaluation.decision, "fail")
        generate_mock.assert_awaited_once()
        evaluate_mock.assert_awaited_once()

    async def test_rule_based_semantic_rejection_uses_one_ai_regeneration(self):
        evaluator = AsyncMock(
            side_effect=[
                evaluation_response("fail"),
                evaluation_response("pass"),
            ]
        )
        with (
            patch(
                "dataController.scraper.extraction_agent_orchestrator.generate_extractor_rule",
                new=AsyncMock(return_value=rule_response(json_rule())),
            ) as generate_mock,
            patch(
                "dataController.scraper.extraction_agent_orchestrator.evaluate_extraction_result",
                new=evaluator,
            ),
        ):
            result = await activate_candidate_rule(
                RAW_JSON,
                source_type="json",
                target_url="https://example.com/notices",
                source_url="https://example.com/notices.json",
                semantic_record_count=2,
                rule_based_candidate=json_rule(),
            )

        self.assertTrue(result.approved)
        self.assertEqual(result.rule_origin, "rule_extractor")
        generate_mock.assert_awaited_once()
        self.assertEqual(evaluator.await_count, 2)


if __name__ == "__main__":
    unittest.main()
