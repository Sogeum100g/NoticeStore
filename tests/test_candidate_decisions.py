import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dataController.selector.candidate_selector import (
    CandidateSelectionResponse,
    _call_gemini_select_candidate,
    _call_llm_select_candidate,
    _call_openai_select_candidate,
    classify_candidate_decision,
)


def candidate(score, **features):
    defaults = {
        "has_repeated_records": False,
        "looks_like_static_asset": False,
        "looks_like_telemetry": False,
        "looks_like_non_content": False,
    }
    defaults.update(features)
    return {"score": score, "features": defaults}


class CandidateDecisionTests(unittest.TestCase):
    def test_strong_single_candidate_is_accepted(self):
        decision, _ = classify_candidate_decision(
            [candidate(30, has_repeated_records=True)]
        )
        self.assertEqual(decision, "accept_rule")

    def test_weak_single_candidate_with_records_is_deferred(self):
        decision, _ = classify_candidate_decision(
            [candidate(8, has_repeated_records=True)]
        )
        self.assertEqual(decision, "defer_to_llm")

    def test_single_candidate_without_records_is_rejected(self):
        decision, _ = classify_candidate_decision([candidate(50)])
        self.assertEqual(decision, "reject_or_observe_more")

    def test_ambiguous_record_candidates_are_deferred(self):
        decision, _ = classify_candidate_decision(
            [
                candidate(25, has_repeated_records=True),
                candidate(23, has_repeated_records=True),
            ]
        )
        self.assertEqual(decision, "defer_to_llm")

    def test_telemetry_is_rejected_even_with_high_score(self):
        decision, _ = classify_candidate_decision(
            [
                candidate(
                    100,
                    has_repeated_records=True,
                    looks_like_telemetry=True,
                )
            ]
        )
        self.assertEqual(decision, "reject_or_observe_more")


class OpenAICandidateSelectionTests(unittest.TestCase):
    @patch.dict(
        "dataController.selector.candidate_selector.os.environ",
        {
            "OPEN_AI_API_KEY_SELECT_API": "test-openai-key",
            "OPENAI_MODEL": "gpt-4.1-mini",
        },
        clear=False,
    )
    @patch("dataController.selector.candidate_selector.OpenAI")
    def test_uses_direct_openai_gpt_4_1_mini_structured_output(self, openai_mock):
        parsed = CandidateSelectionResponse(index=7, reason="반복 게시물 구조가 확인됨")
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
        )
        client = openai_mock.return_value
        client.chat.completions.parse.return_value = response

        result = _call_openai_select_candidate([{"api_index": 7}])

        openai_mock.assert_called_once_with(api_key="test-openai-key")
        call_kwargs = client.chat.completions.parse.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "gpt-4.1-mini")
        self.assertNotIn("reasoning", call_kwargs)
        self.assertIs(call_kwargs["response_format"], CandidateSelectionResponse)
        self.assertEqual(result["index"], 7)
        self.assertEqual(result["reason"], "반복 게시물 구조가 확인됨")
        self.assertEqual(result["_usage"]["provider"], "openai")
        self.assertEqual(result["_usage"]["input_tokens"], 100)
        self.assertEqual(result["_usage"]["output_tokens"], 20)
        self.assertAlmostEqual(result["_usage"]["cost"], 0.0972)

    @patch.dict(
        "dataController.selector.candidate_selector.os.environ",
        {},
        clear=True,
    )
    def test_requires_openai_api_key(self):
        with self.assertRaisesRegex(RuntimeError, "OPEN_AI_API_KEY_SELECT_API"):
            _call_openai_select_candidate([])

    @patch.dict(
        "dataController.selector.candidate_selector.os.environ",
        {"OPEN_AI_API_KEY_SELECT_API": "test-openai-key"},
        clear=True,
    )
    def test_requires_openai_model(self):
        with self.assertRaisesRegex(RuntimeError, "OPENAI_MODEL"):
            _call_openai_select_candidate([])

    @patch.dict(
        "dataController.selector.candidate_selector.os.environ",
        {
            "OPEN_AI_API_KEY_SELECT_API": "test-openai-key",
            "OPENAI_MODEL": "openai/gpt-4.1-mini",
        },
        clear=False,
    )
    @patch("dataController.selector.candidate_selector.OpenAI")
    def test_strips_legacy_proxy_provider_prefix(self, openai_mock):
        parsed = CandidateSelectionResponse(index=-1, reason="유효 후보 없음")
        openai_mock.return_value.chat.completions.parse.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))],
            usage=None,
        )

        _call_openai_select_candidate([])

        call_kwargs = openai_mock.return_value.chat.completions.parse.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "gpt-4.1-mini")


class GeminiCandidateSelectionTests(unittest.TestCase):
    @patch.dict(
        "dataController.selector.candidate_selector.os.environ",
        {
            "GEMINI_API_KEY_SELECT_API": "test-gemini-key",
            "GEMINI_MODEL": "gemini-3.5-flash-lite",
        },
        clear=False,
    )
    @patch("dataController.selector.candidate_selector._create_gemini_client")
    def test_uses_gemini_interactions_structured_output(self, create_client_mock):
        interaction = SimpleNamespace(
            output_text='{"index":7,"reason":"반복 게시물 구조가 확인됨"}',
            usage=SimpleNamespace(
                total_input_tokens=100,
                total_output_tokens=20,
                total_thought_tokens=10,
            ),
        )
        client = create_client_mock.return_value
        client.interactions.create.return_value = interaction

        result = _call_gemini_select_candidate([{"api_index": 7}])

        create_client_mock.assert_called_once_with("test-gemini-key")
        call_kwargs = client.interactions.create.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "gemini-3.5-flash-lite")
        self.assertIn("api_index", call_kwargs["input"])
        self.assertEqual(
            call_kwargs["response_format"]["schema"],
            CandidateSelectionResponse.model_json_schema(),
        )
        self.assertEqual(result["index"], 7)
        self.assertEqual(result["reason"], "반복 게시물 구조가 확인됨")
        self.assertEqual(result["_usage"]["provider"], "gemini")
        self.assertEqual(result["_usage"]["input_tokens"], 100)
        self.assertEqual(result["_usage"]["output_tokens"], 20)
        self.assertEqual(result["_usage"]["thought_tokens"], 10)
        self.assertAlmostEqual(result["_usage"]["cost"], 0.14175)

    @patch.dict(
        "dataController.selector.candidate_selector.os.environ",
        {},
        clear=True,
    )
    def test_requires_gemini_api_key(self):
        with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY_SELECT_API"):
            _call_gemini_select_candidate([])

    @patch.dict(
        "dataController.selector.candidate_selector.os.environ",
        {"GEMINI_API_KEY_SELECT_API": "test-gemini-key"},
        clear=True,
    )
    def test_requires_gemini_model(self):
        with self.assertRaisesRegex(RuntimeError, "GEMINI_MODEL"):
            _call_gemini_select_candidate([])

    @patch.dict(
        "dataController.selector.candidate_selector.os.environ",
        {
            "GEMINI_API_KEY_SELECT_API": "test-gemini-key",
            "GEMINI_MODEL": "models/gemini-3.5-flash-lite",
        },
        clear=True,
    )
    @patch("dataController.selector.candidate_selector._create_gemini_client")
    def test_strips_models_prefix(self, create_client_mock):
        create_client_mock.return_value.interactions.create.return_value = SimpleNamespace(
            output_text='{"index":-1,"reason":"유효 후보 없음"}',
            usage=None,
        )

        _call_gemini_select_candidate([])

        call_kwargs = create_client_mock.return_value.interactions.create.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "gemini-3.5-flash-lite")


class LLMProviderRoutingTests(unittest.TestCase):
    @patch.dict(
        "dataController.selector.candidate_selector.os.environ",
        {"LLM_PROVIDER": "openai"},
        clear=True,
    )
    @patch("dataController.selector.candidate_selector._call_openai_select_candidate")
    def test_routes_to_openai(self, openai_call_mock):
        openai_call_mock.return_value = {"index": -1, "reason": "none"}

        _call_llm_select_candidate([])

        openai_call_mock.assert_called_once_with([])

    @patch.dict(
        "dataController.selector.candidate_selector.os.environ",
        {"LLM_PROVIDER": "gemini"},
        clear=True,
    )
    @patch("dataController.selector.candidate_selector._call_gemini_select_candidate")
    def test_routes_to_gemini(self, gemini_call_mock):
        gemini_call_mock.return_value = {"index": -1, "reason": "none"}

        _call_llm_select_candidate([])

        gemini_call_mock.assert_called_once_with([])

    @patch.dict(
        "dataController.selector.candidate_selector.os.environ",
        {"LLM_PROVIDER": "unsupported"},
        clear=True,
    )
    def test_rejects_unknown_provider(self):
        with self.assertRaisesRegex(RuntimeError, "LLM_PROVIDER"):
            _call_llm_select_candidate([])


if __name__ == "__main__":
    unittest.main()
