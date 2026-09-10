import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dataController.scraper.extraction_agent_client import (
    _call_gemini_structured,
    evaluate_extraction_result_sync,
    generate_extractor_rule_sync,
    select_source_view_sync,
)
from dataController.scraper.extraction_agent_contracts import (
    EvaluatedNoticeEvidenceV2,
    ExtractorRuleV1,
    ResultEvaluationRequestV2,
    ResultEvaluationV2,
    RuleValidationMetrics,
    SourceFieldValuesV1,
    SourceRecordEvidenceV1,
    SourceViewCandidateV1,
    SourceViewSelectionRequestV1,
    SourceViewSelectionV1,
)
from dataController.scraper.structure_sampler import StructureSample


def generated_rule(evidence_id: str = "html-group-0") -> ExtractorRuleV1:
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
                "detail_url": {
                    "kind": "html",
                    "selector": "a",
                    "source": "attribute",
                    "attribute": "href",
                    "transforms": ["urljoin"],
                },
            },
            "evidence_ids": [evidence_id],
        }
    )


def html_sample() -> StructureSample:
    return StructureSample(
        source_type="html",
        payload={
            "version": 1,
            "source_type": "html",
            "untrusted_content": True,
            "record_groups": [
                {
                    "evidence_id": "html-group-0",
                    "suggested_selector": "article.notice",
                    "detected_record_count": 2,
                    "records": [],
                }
            ],
            "fallback_html": None,
            "truncated": False,
        },
        evidence_ids={"html-group-0"},
        truncated=False,
    )


def evaluation_request() -> ResultEvaluationRequestV2:
    return ResultEvaluationRequestV2(
        version=2,
        target_url="https://example.com/notices",
        source_url="https://example.com/notices",
        rule=generated_rule(),
        metrics=RuleValidationMetrics(
            semantic_record_count=2,
            extracted_record_count=2,
            coverage_ratio=1.0,
            missing_title_count=0,
            invalid_detail_url_count=0,
            invalid_date_count=0,
            duplicate_record_count=0,
        ),
        samples=[
            EvaluatedNoticeEvidenceV2(
                title="첫 번째 공지",
                author=None,
                published_at="2026-08-25",
                detail_url="https://example.com/notices/1",
                external_id="1",
                source=SourceRecordEvidenceV1(
                    record_index=0,
                    evidence_id="executed-record-0",
                    source_type="html",
                    record_tag="article",
                    record_attributes={"class": "notice"},
                    visible_text="첫 번째 공지 2026-08-25",
                    field_values=SourceFieldValuesV1(
                        title="첫 번째 공지",
                        published_at="2026-08-25",
                        detail_url="/notices/1",
                        external_id="1",
                    ),
                ),
            )
        ],
        excluded_records=[],
    )


def view_selection_request() -> SourceViewSelectionRequestV1:
    return SourceViewSelectionRequestV1(
        version=1,
        candidates=[
            SourceViewCandidateV1(
                strategy="navigation_preserving",
                payload_hash="a" * 64,
                validation_state="READY",
                reason_codes=[],
                evidence_loss={"navigation": 0.0},
                payload_chars=1200,
                truncated=False,
                groups=[],
            ),
            SourceViewCandidateV1(
                strategy="table_region_preserving",
                payload_hash="b" * 64,
                validation_state="READY",
                reason_codes=[],
                evidence_loss={"records": 0.0},
                payload_chars=1100,
                truncated=False,
                groups=[],
            ),
        ],
    )


class OpenAIExtractionAgentTests(unittest.TestCase):
    @patch.dict(
        "dataController.scraper.extraction_agent_client.os.environ",
        {
            "LLM_PROVIDER": "openai",
            "OPEN_AI_API_KEY_VIEW_SELECTOR": "view-key",
            "OPENAI_VIEW_SELECTOR_MODEL": "gpt-view-model",
        },
        clear=True,
    )
    @patch("dataController.scraper.extraction_agent_client.OpenAI")
    def test_view_selector_can_only_choose_supplied_candidate(self, openai_mock):
        selection = SourceViewSelectionV1(
            version=1,
            strategy="table_region_preserving",
            payload_hash="b" * 64,
            confidence=0.91,
            reason="표 레코드 경계가 더 명확합니다.",
        )
        openai_mock.return_value.chat.completions.parse.return_value = (
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(parsed=selection))],
                usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
            )
        )

        result = select_source_view_sync(view_selection_request())

        call = openai_mock.return_value.chat.completions.parse.call_args.kwargs
        self.assertEqual(call["model"], "gpt-view-model")
        self.assertIs(call["response_format"], SourceViewSelectionV1)
        self.assertIn('"payload_hash":"bbbb', call["messages"][0]["content"])
        self.assertEqual(result.stage, "view_selector")
        self.assertEqual(result.value.strategy, "table_region_preserving")

    @patch(
        "dataController.scraper.extraction_agent_client._call_structured"
    )
    def test_view_selector_rejects_fabricated_candidate(self, call_mock):
        call_mock.return_value = SimpleNamespace(
            stage="view_selector",
            value=SourceViewSelectionV1(
                version=1,
                strategy="table_region_preserving",
                payload_hash="c" * 64,
                confidence=0.95,
                reason="fabricated",
            ),
            usage={},
        )

        with self.assertRaisesRegex(ValueError, "입력에 없는 후보"):
            select_source_view_sync(view_selection_request())

    @patch.dict(
        "dataController.scraper.extraction_agent_client.os.environ",
        {
            "LLM_PROVIDER": "openai",
            "OPEN_AI_API_KEY_RULE_EXTRACTOR": "rule-key",
            "OPENAI_RULE_EXTRACTOR_MODEL": "gpt-rule-model",
        },
        clear=True,
    )
    @patch("dataController.scraper.extraction_agent_client.OpenAI")
    def test_rule_extractor_uses_dedicated_structured_output(self, openai_mock):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(parsed=generated_rule())
                )
            ],
            usage=SimpleNamespace(prompt_tokens=200, completion_tokens=50),
        )
        openai_mock.return_value.chat.completions.parse.return_value = response

        with self.assertLogs(
            "dataController.scraper.extraction_agent_client",
            level="INFO",
        ) as captured_logs:
            result = generate_extractor_rule_sync(
                target_url="https://example.com/notices",
                source_url="https://example.com/notices",
                sample=html_sample(),
            )

        openai_mock.assert_called_once_with(api_key="rule-key")
        call = openai_mock.return_value.chat.completions.parse.call_args.kwargs
        self.assertEqual(call["model"], "gpt-rule-model")
        self.assertIs(call["response_format"], ExtractorRuleV1)
        self.assertIn("untrusted_content", call["messages"][0]["content"])
        self.assertEqual(result.stage, "rule_extractor")
        self.assertEqual(result.usage["provider"], "openai")
        self.assertEqual(result.value.record_selector, "article.notice")
        usage_log = "\n".join(captured_logs.output)
        self.assertIn("rule_extractor API 호출 완료", usage_log)
        self.assertIn("tokens=(in:200 / out:50 / thought:0)", usage_log)
        self.assertIn("예상 비용=₩0.2160", usage_log)

    @patch.dict(
        "dataController.scraper.extraction_agent_client.os.environ",
        {
            "LLM_PROVIDER": "openai",
            "OPEN_AI_API_KEY_RULE_EXTRACTOR": "rule-key",
            "OPENAI_RULE_EXTRACTOR_MODEL": "gpt-rule-model",
        },
        clear=True,
    )
    @patch("dataController.scraper.extraction_agent_client.OpenAI")
    def test_rule_extractor_rejects_fabricated_evidence_id(self, openai_mock):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        parsed=generated_rule("fabricated-evidence")
                    )
                )
            ],
            usage=None,
        )
        openai_mock.return_value.chat.completions.parse.return_value = response

        with self.assertRaisesRegex(ValueError, "입력에 없는 evidence"):
            generate_extractor_rule_sync(
                target_url="https://example.com/notices",
                source_url="https://example.com/notices",
                sample=html_sample(),
            )

    @patch.dict(
        "dataController.scraper.extraction_agent_client.os.environ",
        {
            "LLM_PROVIDER": "openai",
            "OPEN_AI_API_KEY_RESULT_EVALUATOR": "evaluation-key",
            "OPENAI_RESULT_EVALUATOR_MODEL": "gpt-evaluation-model",
        },
        clear=True,
    )
    @patch("dataController.scraper.extraction_agent_client.OpenAI")
    def test_result_evaluator_uses_separate_key_and_contract(self, openai_mock):
        evaluation = ResultEvaluationV2(
            version=2,
            decision="pass",
            confidence=0.96,
            reason_codes=[],
            affected_fields=[],
            reason="공지 목록과 원본 근거가 일치합니다.",
        )
        openai_mock.return_value.chat.completions.parse.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=evaluation))],
            usage=SimpleNamespace(prompt_tokens=300, completion_tokens=40),
        )

        with self.assertLogs(
            "dataController.scraper.extraction_agent_client",
            level="INFO",
        ) as captured_logs:
            result = evaluate_extraction_result_sync(evaluation_request())

        openai_mock.assert_called_once_with(api_key="evaluation-key")
        call = openai_mock.return_value.chat.completions.parse.call_args.kwargs
        self.assertEqual(call["model"], "gpt-evaluation-model")
        self.assertIs(call["response_format"], ResultEvaluationV2)
        prompt = call["messages"][0]["content"]
        self.assertIn('"version":2', prompt)
        self.assertIn('"field_values"', prompt)
        self.assertNotIn("source_excerpt", prompt)
        self.assertNotIn('"author":null', prompt)
        self.assertEqual(result.value.decision, "pass")
        usage_log = "\n".join(captured_logs.output)
        self.assertIn("result_evaluator API 호출 완료", usage_log)
        self.assertIn("tokens=(in:300 / out:40 / thought:0)", usage_log)
        self.assertIn("예상 비용=₩0.2484", usage_log)


class GeminiExtractionAgentTests(unittest.TestCase):
    @patch.dict(
        "dataController.scraper.extraction_agent_client.os.environ",
        {
            "GEMINI_API_KEY_RESULT_EVALUATOR": "evaluation-key",
            "GEMINI_RESULT_EVALUATOR_MODEL": "models/gemini-evaluator",
        },
        clear=True,
    )
    @patch(
        "dataController.scraper.extraction_agent_client._create_gemini_client"
    )
    def test_gemini_result_evaluator_uses_json_schema(self, create_client_mock):
        create_client_mock.return_value.interactions.create.return_value = (
            SimpleNamespace(
                output_text=(
                    '{"version":2,"decision":"fail","confidence":0.91,'
                    '"reason_codes":["WRONG_CONTENT_REGION"],'
                    '"affected_fields":["title"],'
                    '"reason":"추천 카드 영역입니다."}'
                ),
                usage=SimpleNamespace(
                    total_input_tokens=200,
                    total_output_tokens=30,
                    total_thought_tokens=10,
                ),
            )
        )

        with self.assertLogs(
            "dataController.scraper.extraction_agent_client",
            level="INFO",
        ) as captured_logs:
            result = _call_gemini_structured(
                stage="result_evaluator",
                prompt="fixture",
                response_model=ResultEvaluationV2,
            )

        create_client_mock.assert_called_once_with("evaluation-key")
        call = create_client_mock.return_value.interactions.create.call_args.kwargs
        self.assertEqual(call["model"], "gemini-evaluator")
        self.assertEqual(
            call["response_format"]["schema"],
            ResultEvaluationV2.model_json_schema(),
        )
        self.assertEqual(result.value.decision, "fail")
        self.assertEqual(result.usage["thought_tokens"], 10)
        usage_log = "\n".join(captured_logs.output)
        self.assertIn("result_evaluator API 호출 완료", usage_log)
        self.assertIn("tokens=(in:200 / out:30 / thought:10)", usage_log)
        self.assertIn("예상 비용=₩0.2160", usage_log)


if __name__ == "__main__":
    unittest.main()
