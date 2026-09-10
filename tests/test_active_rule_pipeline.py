import json
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from dataController.scraper.active_rule_config import (
    ACTIVE_RULE_FORMAT,
    build_active_rule_config,
    execute_active_rule_config,
)
from dataController.scraper.deterministic_extractor import (
    extract_notices_deterministically,
)
from dataController.scraper.declarative_rule_executor import execute_extractor_rule
from dataController.scraper.extraction_agent_client import StructuredAgentResponse
from dataController.scraper.extraction_agent_contracts import (
    ExtractorRuleV1,
    ResultEvaluationV2,
)
from dataController.scraper.extraction_agent_orchestrator import RuleActivationResult
from dataController.scraper.rule_candidate_adapter import build_rule_based_candidate
from dataController.scraper.scrape_auto import (
    _agent_run_telemetry,
    _complete_structured_processing,
    _extraction_agent_enabled,
    _extract_with_agent_pipeline,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _pass_evaluation() -> ResultEvaluationV2:
    return ResultEvaluationV2(
        version=2,
        decision="pass",
        confidence=0.96,
        reason_codes=[],
        affected_fields=[],
        reason="공지 목록과 일치합니다.",
    )


def _fail_evaluation() -> ResultEvaluationV2:
    return ResultEvaluationV2(
        version=2,
        decision="fail",
        confidence=0.94,
        reason_codes=["NON_NOTICE_CONTENT"],
        affected_fields=["title"],
        reason="공지 목록이 아닙니다.",
    )


def _evaluation_response(value: ResultEvaluationV2) -> StructuredAgentResponse:
    return StructuredAgentResponse(
        stage="result_evaluator",
        value=value,
        usage={"provider": "fixture", "input_tokens": 10, "output_tokens": 3},
    )


def _dcinside_rule_response() -> StructuredAgentResponse:
    rule = ExtractorRuleV1.model_validate(
        {
            "version": 1,
            "source_type": "html",
            "record_selector": "tr.us-post",
            "records_path": None,
            "fields": {
                "title": {
                    "kind": "html",
                    "selector": "td.gall_tit a",
                    "source": "text",
                    "transforms": ["normalize_space"],
                },
                "author": {
                    "kind": "html",
                    "selector": "td.gall_writer",
                    "source": "text",
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
    return StructuredAgentResponse(
        stage="rule_extractor",
        value=rule,
        usage={"provider": "fixture", "input_tokens": 10, "output_tokens": 5},
    )


class RuleCandidateAdapterTests(unittest.TestCase):
    def test_json_legacy_result_converts_to_declarative_candidate(self):
        raw = json.loads((FIXTURE_DIR / "notices.json").read_text(encoding="utf-8"))
        result = extract_notices_deterministically(
            raw,
            content_type="application/json",
            base_url="https://public.example/notices",
        )

        rule = build_rule_based_candidate(raw, result)

        self.assertIsNotNone(rule)
        self.assertEqual(rule.source_type, "json")
        self.assertEqual(rule.records_path, "$.response.items")
        self.assertEqual(rule.fields.title.path, "$.title")

    def test_derived_json_detail_urls_survive_candidate_conversion(self):
        raw = {
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
        }
        base_url = (
            "https://careers.kakao.com/jobs"
            "?company=KAKAO&part=TECHNOLOGY&page=1"
        )
        result = extract_notices_deterministically(
            raw,
            content_type="application/json",
            base_url=base_url,
        )

        rule = build_rule_based_candidate(raw, result)
        execution = execute_extractor_rule(raw, rule=rule, base_url=base_url)

        self.assertIsNotNone(rule.fields.detail_url)
        self.assertEqual(
            rule.fields.detail_url.template,
            (
                "https://careers.kakao.com/jobs/{external_id}"
                "?company=KAKAO&page=1&part=TECHNOLOGY"
            ),
        )
        self.assertEqual(
            [notice["detail_url"] for notice in execution.notices],
            [notice["detail_url"] for notice in result.notices],
        )

    def test_html_legacy_result_converts_and_reexecutes(self):
        raw = (FIXTURE_DIR / "notices.html").read_text(encoding="utf-8")
        result = extract_notices_deterministically(
            raw,
            content_type="text/html",
            base_url="https://public.example/notices",
        )
        rule = build_rule_based_candidate(raw, result)

        self.assertIsNotNone(rule)
        self.assertEqual(rule.source_type, "html")
        self.assertIsNotNone(rule.fields.detail_url)
        execution = execute_extractor_rule(
            raw,
            rule=rule,
            base_url="https://public.example/notices",
        )
        self.assertEqual(len(execution.notices), 2)
        self.assertEqual(execution.notices[0]["author"], "운영팀")


class ActiveRuleConfigTests(unittest.TestCase):
    def test_rejected_activation_cannot_be_persisted(self):
        rejected = RuleActivationResult(
            status="rejected",
            rule_origin="rule_based",
            rule=None,
            approved_notices=[],
            execution=None,
            hard_gate=None,
            evaluation=None,
            reason="fail",
        )
        with self.assertRaises(ValueError):
            build_active_rule_config(rejected)

    def test_invalid_active_envelope_fails_closed(self):
        result = execute_active_rule_config(
            {"items": []},
            config={
                "format": ACTIVE_RULE_FORMAT,
                "activation": {"status": "active"},
                "rule": {"version": 999},
            },
            target_url="https://public.example/notices",
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.notices, [])

    def test_stage_usage_is_aggregated_without_losing_stage_detail(self):
        telemetry = _agent_run_telemetry(
            {
                "_llm_used": True,
                "_llm_usage": {
                    "provider": "openai",
                    "input_tokens": 5,
                    "output_tokens": 2,
                    "cost": 0.1,
                },
                "_extraction_agent_usage": [
                    {
                        "stage": "result_evaluator",
                        "provider": "openai",
                        "input_tokens": 7,
                        "output_tokens": 3,
                        "cost": 0.2,
                    }
                ],
                "_rule_activation": {
                    "status": "approved",
                    "evaluator_decision": "pass",
                    "evaluator_confidence": 0.96,
                },
            }
        )
        self.assertEqual(
            [item["stage"] for item in telemetry["stages"]],
            ["api_selector", "result_evaluator"],
        )
        self.assertEqual(telemetry["input_tokens"], 12)
        self.assertEqual(telemetry["output_tokens"], 5)
        self.assertAlmostEqual(telemetry["cost"], 0.3)

    def test_coverage_diagnostics_are_kept_in_run_telemetry(self):
        telemetry = _agent_run_telemetry(
            {
                "_coverage_diagnostics": {
                    "reason_codes": ["COVERAGE_MISMATCH"],
                    "semantic_record_count": 27,
                    "extracted_record_count": 10,
                    "extraction_ratio": 10 / 27,
                }
            }
        )

        self.assertEqual(len(telemetry["stages"]), 1)
        stage = telemetry["stages"][0]
        self.assertEqual(stage["stage"], "coverage_diagnostics")
        self.assertEqual(stage["provider"], "local")
        self.assertEqual(stage["reason_codes"], ["COVERAGE_MISMATCH"])
        self.assertFalse(telemetry["llm_used"])

    def test_source_view_recovery_diagnostics_survive_run_telemetry(self):
        source_view = {
            "strategy": "default_structure_sampler",
            "validation": {
                "state": "REPARSE_REQUIRED",
                "reason_codes": ["NAVIGATION_EVIDENCE_LOST"],
                "evidence_loss": {
                    "anchor_count": {"raw": 12, "view": 0},
                },
            },
        }
        activation_diagnostics = {
            "recovery_state": "REPARSE_REQUIRED",
            "source_view_attempt": source_view,
        }
        telemetry = _agent_run_telemetry(
            {
                "_extraction_agent_usage": [
                    {
                        "stage": "structure_sampler",
                        "provider": "local",
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost": 0.0,
                        "source_view": source_view,
                    },
                    {
                        "stage": "rule_activation",
                        "provider": "local",
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost": 0.0,
                        "status": "rejected",
                        "failure_code": "RULE_GENERATION_FAILED",
                        "diagnostics": activation_diagnostics,
                    },
                ],
                "_rule_activation": {
                    "status": "rejected",
                    "reason": "규칙 생성 실패",
                    "failure_code": "RULE_GENERATION_FAILED",
                    "diagnostics": activation_diagnostics,
                },
            }
        )

        self.assertEqual(
            telemetry["stages"][0]["source_view"]["validation"]["state"],
            "REPARSE_REQUIRED",
        )
        self.assertEqual(
            telemetry["stages"][1]["diagnostics"]["recovery_state"],
            "REPARSE_REQUIRED",
        )
        self.assertEqual(telemetry["activation_status"], "rejected")

    def test_failed_activation_cannot_persist_api_or_notices(self):
        api = {
            "site_id": 7,
            "_pending_persistence": True,
            "_rule_activation": {
                "status": "rejected",
                "reason": "공지 목록이 아닙니다.",
                "evaluator_decision": "fail",
                "evaluator_confidence": 0.94,
            },
            "_extraction_agent_usage": [
                {
                    "stage": "result_evaluator",
                    "input_tokens": 10,
                    "output_tokens": 3,
                    "cost": 0.2,
                }
            ],
        }
        with (
            patch("dataController.scraper.scrape_auto.save_api") as save_api,
            patch(
                "dataController.scraper.scrape_auto.sync_notices_to_db"
            ) as sync_notices,
            patch(
                "dataController.scraper.scrape_auto.notice_repo."
                "update_site_crawl_state"
            ),
            patch(
                "dataController.scraper.scrape_auto.notice_repo."
                "finish_crawl_run"
            ) as finish_run,
        ):
            status = _complete_structured_processing(
                api=api,
                target_url="https://public.example/notices",
                site_id=7,
                api_url="https://public.example/notices.json",
                new_hash="observed-hash",
                structured={
                    "status": "error",
                    "notices": [],
                    "error_msg": "공지 목록이 아닙니다.",
                },
                crawl_run_id=11,
            )

        self.assertEqual(status, "failed")
        save_api.assert_not_called()
        sync_notices.assert_not_called()
        self.assertEqual(
            finish_run.call_args.kwargs["rule_activation_status"],
            "rejected",
        )
        self.assertEqual(
            finish_run.call_args.kwargs["evaluator_decision"],
            "fail",
        )


class RolloutPolicyTests(unittest.TestCase):
    def test_kill_switch_overrides_rollout_mode(self):
        with patch.dict(
            os.environ,
            {
                "EXTRACTION_AGENT_ENABLED": "false",
                "EXTRACTION_AGENT_ROLLOUT_MODE": "all",
            },
            clear=True,
        ):
            self.assertFalse(
                _extraction_agent_enabled({"_pending_persistence": True})
            )

    def test_new_sites_mode_excludes_cached_legacy_api(self):
        with patch.dict(
            os.environ,
            {
                "EXTRACTION_AGENT_ENABLED": "true",
                "EXTRACTION_AGENT_ROLLOUT_MODE": "new_sites",
            },
            clear=True,
        ):
            self.assertTrue(
                _extraction_agent_enabled({"_pending_persistence": True})
            )
            self.assertFalse(
                _extraction_agent_enabled(
                    {
                        "_pending_persistence": False,
                        "extractor_config": {
                            "version": 5,
                            "source_type": "html",
                        },
                    }
                )
            )

    def test_new_sites_mode_allows_recovery_of_active_agent_rule(self):
        with patch.dict(
            os.environ,
            {
                "EXTRACTION_AGENT_ENABLED": "true",
                "EXTRACTION_AGENT_ROLLOUT_MODE": "new_sites",
            },
            clear=True,
        ):
            self.assertTrue(
                _extraction_agent_enabled(
                    {
                        "_pending_persistence": False,
                        "extractor_config": {
                            "format": ACTIVE_RULE_FORMAT,
                            "activation": {"status": "active"},
                            "rule": {"version": 1},
                        },
                    }
                )
            )

    def test_unknown_rollout_mode_fails_closed(self):
        with patch.dict(
            os.environ,
            {
                "EXTRACTION_AGENT_ENABLED": "true",
                "EXTRACTION_AGENT_ROLLOUT_MODE": "surprise",
            },
            clear=True,
        ):
            self.assertFalse(
                _extraction_agent_enabled({"_pending_persistence": True})
            )

    def test_all_mode_can_migrate_cached_legacy_api(self):
        with patch.dict(
            os.environ,
            {
                "EXTRACTION_AGENT_ENABLED": "true",
                "EXTRACTION_AGENT_ROLLOUT_MODE": "all",
            },
            clear=True,
        ):
            self.assertTrue(
                _extraction_agent_enabled({"_pending_persistence": False})
            )


class AgentPipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        template_patch = patch("repositories.notice_repo.select_dcinside_rule_templates", return_value=[])
        self.templates = template_patch.start()
        self.addCleanup(template_patch.stop)

    async def test_page_wide_banner_count_does_not_force_rule_regeneration(self):
        event_rows = "".join(
            f'<li><a href="/News/Event/{1300 + index}">이벤트 배너 {index}</a>'
            f'<time>2026.09.{index + 1:02d}</time></li>'
            for index in range(8)
        )
        notice_rows = "".join(
            '<li><p><a href="/News/Notice/All/{id}">공지 제목 {index}</a></p>'
            '<div class="heart_date"><dd>2026.09.{day:02d}</dd></div></li>'.format(
                id=149800 + index,
                index=index,
                day=index + 1,
            )
            for index in range(4)
        )
        raw = (
            f'<div class="event_all_bannerwrap"><ul>{event_rows}</ul></div>'
            f'<div class="news_board"><ul>{notice_rows}</ul></div>'
        )
        api = {
            "site_id": 57,
            "_pending_persistence": True,
            "validation_analysis": {"semantic_record_count": 12},
        }

        with (
            patch.dict(os.environ, {"EXTRACTION_AGENT_ENABLED": "true"}),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "generate_extractor_rule",
                new=AsyncMock(),
            ) as generate,
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "evaluate_extraction_result",
                new=AsyncMock(
                    return_value=_evaluation_response(_pass_evaluation())
                ),
            ) as evaluate,
        ):
            result = await _extract_with_agent_pipeline(
                raw,
                content_type="text/html",
                target_url="https://maplestory.example/News/Notice/All",
                source_url="https://maplestory.example/News/Notice/All",
                api=api,
            )
            api["extractor_config"] = result.extractor_config
            api["_pending_persistence"] = False
            recurring = await _extract_with_agent_pipeline(
                raw,
                content_type="text/html",
                target_url="https://maplestory.example/News/Notice/All",
                source_url="https://maplestory.example/News/Notice/All",
                api=api,
            )

        self.assertEqual(result.status, "success")
        self.assertEqual(recurring.status, "success")
        self.assertEqual(len(result.notices), 4)
        self.assertEqual(result.notices[0]["external_id"], "149800")
        generate.assert_not_awaited()
        evaluate.assert_awaited_once()
        request = evaluate.await_args.args[0]
        self.assertEqual(
            request.semantic_diagnostic_codes,
            ["COVERAGE_MISMATCH"],
        )
        self.assertEqual(request.metrics.semantic_record_count, 12)
        self.assertEqual(request.metrics.baseline_record_count, 4)
        self.assertEqual(
            result.extractor_config["activation"][
                "semantic_diagnostic_codes"
            ],
            ["COVERAGE_MISMATCH"],
        )

    async def test_changed_count_diagnostic_reactivates_evaluator(self):
        raw = json.loads(
            (FIXTURE_DIR / "notices.json").read_text(encoding="utf-8")
        )
        api = {
            "site_id": 7,
            "_pending_persistence": True,
            "validation_analysis": {"semantic_record_count": 2},
        }
        with (
            patch.dict(os.environ, {"EXTRACTION_AGENT_ENABLED": "true"}),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "generate_extractor_rule",
                new=AsyncMock(),
            ) as generate,
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "evaluate_extraction_result",
                new=AsyncMock(
                    return_value=_evaluation_response(_pass_evaluation())
                ),
            ) as evaluate,
        ):
            first = await _extract_with_agent_pipeline(
                raw,
                content_type="application/json",
                target_url="https://public.example/notices",
                source_url="https://public.example/notices.json",
                api=api,
            )
            api["extractor_config"] = first.extractor_config
            api["_pending_persistence"] = False
            api["validation_analysis"]["semantic_record_count"] = 10
            reevaluated = await _extract_with_agent_pipeline(
                raw,
                content_type="application/json",
                target_url="https://public.example/notices",
                source_url="https://public.example/notices.json",
                api=api,
            )

        self.assertEqual(first.status, "success")
        self.assertEqual(reevaluated.status, "success")
        self.assertEqual(
            reevaluated.extractor_config["activation"][
                "semantic_diagnostic_codes"
            ],
            ["COVERAGE_MISMATCH"],
        )
        generate.assert_not_awaited()
        self.assertEqual(evaluate.await_count, 2)

    async def test_kill_switch_defers_changed_count_reevaluation(self):
        raw = json.loads(
            (FIXTURE_DIR / "notices.json").read_text(encoding="utf-8")
        )
        api = {
            "site_id": 7,
            "_pending_persistence": True,
            "validation_analysis": {"semantic_record_count": 2},
        }
        evaluator = AsyncMock(
            return_value=_evaluation_response(_pass_evaluation())
        )
        with (
            patch.dict(os.environ, {"EXTRACTION_AGENT_ENABLED": "true"}),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "generate_extractor_rule",
                new=AsyncMock(),
            ),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "evaluate_extraction_result",
                new=evaluator,
            ),
        ):
            first = await _extract_with_agent_pipeline(
                raw,
                content_type="application/json",
                target_url="https://public.example/notices",
                source_url="https://public.example/notices.json",
                api=api,
            )

        api["extractor_config"] = first.extractor_config
        api["_pending_persistence"] = False
        api["validation_analysis"]["semantic_record_count"] = 10
        with patch.dict(
            os.environ,
            {"EXTRACTION_AGENT_ENABLED": "false"},
        ):
            deferred = await _extract_with_agent_pipeline(
                raw,
                content_type="application/json",
                target_url="https://public.example/notices",
                source_url="https://public.example/notices.json",
                api=api,
            )

        self.assertEqual(deferred.status, "success")
        self.assertEqual(len(deferred.notices), 2)
        self.assertEqual(
            api["_rule_activation"]["status"],
            "reused_pending_reevaluation",
        )
        evaluator.assert_awaited_once()

    async def test_other_gallery_template_is_evaluated_then_reused_without_ai(self):
        template = {
            "format": ACTIVE_RULE_FORMAT,
            "source_type": "html",
            "detail_url_base_version": 2,
            "rule": _dcinside_rule_response().value.model_dump(mode="json"),
            "activation": {"status": "active", "evaluation": _pass_evaluation().model_dump(mode="json")},
        }
        self.templates.return_value = [{"site_id": 48, "extractor_config": template}]
        for gallery, route in (("chicken", "board"), ("san14", "mgallery/board")):
            with self.subTest(gallery=gallery):
                raw = (FIXTURE_DIR / "dcinside_board.html").read_text().replace("id=hair", f"id={gallery}").replace("/board/view/", f"/{route}/view/")
                api = {"site_id": 91, "_pending_persistence": True, "validation_analysis": {"semantic_record_count": 3}}
                target = f"https://m.dcinside.com/board/{gallery}?recommend=1"
                source = f"https://gall.dcinside.com/{route}/lists/?id={gallery}&exception_mode=recommend"
                with (
                    patch.dict(os.environ, {"EXTRACTION_AGENT_ENABLED": "true"}),
                    patch("dataController.scraper.extraction_agent_orchestrator.generate_extractor_rule", new=AsyncMock()) as generate,
                    patch("dataController.scraper.extraction_agent_orchestrator.evaluate_extraction_result", new=AsyncMock(return_value=_evaluation_response(_pass_evaluation()))) as evaluate,
                ):
                    result = await _extract_with_agent_pipeline(raw, content_type="text/html", target_url=target, source_url=source, api=api)
                    self.assertEqual(result.status, "success")
                    self.assertEqual(result.extractor_config["activation"]["rule_origin"], "site_template")
                    self.assertEqual(api["_rule_activation"]["diagnostics"]["template_site_id"], 48)
                    self.assertTrue(all(n["detail_url"].startswith(f"https://m.dcinside.com/board/{gallery}/") for n in result.notices))
                    api["extractor_config"] = result.extractor_config
                    api["_pending_persistence"] = False
                    reused = await _extract_with_agent_pipeline(raw, content_type="text/html", target_url=target, source_url=source, api=api)
                    self.assertEqual(reused.status, "success")
                    evaluate.assert_awaited_once()
                    generate.assert_not_awaited()

    async def test_template_does_not_bypass_semantic_rejection(self):
        self.templates.return_value = [{"site_id": 48, "extractor_config": {
            "format": ACTIVE_RULE_FORMAT,
            "rule": _dcinside_rule_response().value.model_dump(mode="json"),
            "activation": {"status": "active"},
        }}]
        raw = (FIXTURE_DIR / "dcinside_board.html").read_text()
        with (
            patch.dict(os.environ, {"EXTRACTION_AGENT_ENABLED": "true"}),
            patch("dataController.scraper.extraction_agent_orchestrator.generate_extractor_rule", new=AsyncMock(side_effect=RuntimeError("unavailable"))),
            patch("dataController.scraper.extraction_agent_orchestrator.evaluate_extraction_result", new=AsyncMock(return_value=_evaluation_response(_fail_evaluation()))),
        ):
            result = await _extract_with_agent_pipeline(raw, content_type="text/html",
                target_url="https://m.dcinside.com/board/hair",
                source_url="https://gall.dcinside.com/board/lists/?id=hair",
                api={"site_id": 91, "_pending_persistence": True})
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.notices, [])

    async def test_own_old_gallery_rule_is_reapproved_before_regeneration(self):
        config = {"format": ACTIVE_RULE_FORMAT, "source_type": "html", "detail_url_base_version": 2,
            "rule": _dcinside_rule_response().value.model_dump(mode="json"), "activation": {"status": "active"}}
        with (
            patch.dict(os.environ, {"EXTRACTION_AGENT_ENABLED": "true", "EXTRACTION_AGENT_ROLLOUT_MODE": "all"}),
            patch("dataController.scraper.extraction_agent_orchestrator.generate_extractor_rule", new=AsyncMock()) as generate,
            patch("dataController.scraper.extraction_agent_orchestrator.evaluate_extraction_result", new=AsyncMock(return_value=_evaluation_response(_pass_evaluation()))) as evaluate,
        ):
            result = await _extract_with_agent_pipeline((FIXTURE_DIR / "dcinside_board.html").read_text(),
                content_type="text/html", target_url="https://m.dcinside.com/board/hair",
                source_url="https://gall.dcinside.com/board/lists/?id=hair",
                api={"site_id": 48, "extractor_config": config})
        self.assertEqual(result.status, "success")
        self.assertEqual(result.extractor_config["detail_url_base_version"], 4)
        generate.assert_not_awaited()
        evaluate.assert_awaited_once()

    async def test_old_json_active_rule_reactivates_with_derived_detail_urls(self):
        raw = {
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
        }
        old_rule = ExtractorRuleV1.model_validate(
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
                    "external_id": {
                        "kind": "json",
                        "path": "$.realId",
                        "transforms": ["normalize_space"],
                    },
                },
                "evidence_ids": ["legacy-json-rule"],
            }
        )
        api = {
            "site_id": 67,
            "_pending_persistence": False,
            "validation_analysis": {"semantic_record_count": 2},
            "extractor_config": {
                "format": ACTIVE_RULE_FORMAT,
                "source_type": "json",
                "rule": old_rule.model_dump(mode="json"),
                "activation": {
                    "status": "active",
                    "evaluation": _pass_evaluation().model_dump(mode="json"),
                },
                "notice_identity_version": 1,
            },
        }
        target_url = (
            "https://careers.kakao.com/jobs"
            "?company=KAKAO&part=TECHNOLOGY&page=1"
        )

        with (
            patch.dict(os.environ, {"EXTRACTION_AGENT_ENABLED": "true"}),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "generate_extractor_rule",
                new=AsyncMock(),
            ) as generate,
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "evaluate_extraction_result",
                new=AsyncMock(return_value=_evaluation_response(_pass_evaluation())),
            ) as evaluate,
        ):
            result = await _extract_with_agent_pipeline(
                raw,
                content_type="application/json",
                target_url=target_url,
                source_url="https://careers.kakao.com/api/jobs",
                api=api,
            )

        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.notices[0]["detail_url"],
            (
                "https://careers.kakao.com/jobs/P-14472"
                "?company=KAKAO&page=1&part=TECHNOLOGY"
            ),
        )
        self.assertEqual(result.extractor_config["json_detail_template_version"], 1)
        self.assertIsNotNone(
            result.extractor_config["rule"]["fields"]["detail_url"]
        )
        generate.assert_not_awaited()
        evaluate.assert_awaited_once()

    async def test_html_detail_urls_use_source_document_across_activation_and_reuse(self):
        raw = (FIXTURE_DIR / "dcinside_board.html").read_text(encoding="utf-8")
        api = {
            "site_id": 48,
            "_pending_persistence": True,
            "validation_analysis": {"semantic_record_count": 3},
        }
        target_url = "https://m.dcinside.com/board/hair?recommend=1"
        source_url = "https://gall.dcinside.com/board/lists/?id=hair"

        with (
            patch.dict(os.environ, {"EXTRACTION_AGENT_ENABLED": "true"}),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "generate_extractor_rule",
                new=AsyncMock(return_value=_dcinside_rule_response()),
            ),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "evaluate_extraction_result",
                new=AsyncMock(return_value=_evaluation_response(_pass_evaluation())),
            ),
        ):
            first = await _extract_with_agent_pipeline(
                raw,
                content_type="text/html; charset=UTF-8",
                target_url=target_url,
                source_url=source_url,
                api=api,
            )
            api["extractor_config"] = first.extractor_config
            api["_pending_persistence"] = False
            second = await _extract_with_agent_pipeline(
                raw,
                content_type="text/html; charset=UTF-8",
                target_url=target_url,
                source_url=source_url,
                api=api,
            )

        expected = "https://m.dcinside.com/board/hair/328766"
        self.assertEqual(first.notices[0]["detail_url"], expected)
        self.assertEqual(second.notices[0]["detail_url"], expected)
        self.assertEqual(first.notices[0]["url"], target_url)

    async def test_first_run_evaluates_once_then_recurring_run_uses_zero_ai(self):
        raw = json.loads((FIXTURE_DIR / "notices.json").read_text(encoding="utf-8"))
        api = {
            "site_id": 7,
            "_pending_persistence": True,
            "validation_analysis": {"semantic_record_count": 2},
        }
        env = {"EXTRACTION_AGENT_ENABLED": "true"}
        with (
            patch.dict(os.environ, env),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "generate_extractor_rule",
                new=AsyncMock(),
            ) as generate,
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "evaluate_extraction_result",
                new=AsyncMock(return_value=_evaluation_response(_pass_evaluation())),
            ) as evaluate,
        ):
            first = await _extract_with_agent_pipeline(
                raw,
                content_type="application/json",
                target_url="https://public.example/notices",
                source_url="https://public.example/notices.json",
                api=api,
            )
            api["extractor_config"] = first.extractor_config
            second = await _extract_with_agent_pipeline(
                raw,
                content_type="application/json",
                target_url="https://public.example/notices",
                source_url="https://public.example/notices.json",
                api=api,
            )

        self.assertEqual(first.status, "success")
        self.assertEqual(first.extractor_config["format"], ACTIVE_RULE_FORMAT)
        self.assertEqual(second.status, "success")
        self.assertEqual(len(second.notices), 2)
        generate.assert_not_awaited()
        evaluate.assert_awaited_once()

    async def test_evaluator_fail_returns_no_notices_and_no_active_config(self):
        raw = json.loads((FIXTURE_DIR / "notices.json").read_text(encoding="utf-8"))
        api = {
            "site_id": 7,
            "_pending_persistence": True,
            "validation_analysis": {"semantic_record_count": 2},
        }
        with (
            patch.dict(os.environ, {"EXTRACTION_AGENT_ENABLED": "true"}),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "generate_extractor_rule",
                new=AsyncMock(side_effect=RuntimeError("fixture regeneration failed")),
            ),
            patch(
                "dataController.scraper.extraction_agent_orchestrator."
                "evaluate_extraction_result",
                new=AsyncMock(return_value=_evaluation_response(_fail_evaluation())),
            ) as evaluate,
        ):
            result = await _extract_with_agent_pipeline(
                raw,
                content_type="application/json",
                target_url="https://public.example/notices",
                source_url="https://public.example/notices.json",
                api=api,
            )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.notices, [])
        self.assertIsNone(result.extractor_config)
        evaluate.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
