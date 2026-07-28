import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dataController.selector.candidate_selector import (
    CandidateSelectionResponse,
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
        {"OPEN_AI_API_KEY_SELECT_API": "test-key"},
        clear=False,
    )
    @patch("dataController.selector.candidate_selector.OpenAI")
    def test_uses_gpt_5_nano_structured_output(self, openai_mock):
        parsed = CandidateSelectionResponse(index=7, reason="반복 게시물 구조가 확인됨")
        response = SimpleNamespace(
            output_parsed=parsed,
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        )
        client = openai_mock.return_value
        client.responses.parse.return_value = response

        result = _call_openai_select_candidate([{"api_index": 7}])

        openai_mock.assert_called_once_with(api_key="test-key")
        call_kwargs = client.responses.parse.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "gpt-5-nano")
        self.assertIs(call_kwargs["text_format"], CandidateSelectionResponse)
        self.assertEqual(result["index"], 7)
        self.assertEqual(result["reason"], "반복 게시물 구조가 확인됨")
        self.assertEqual(result["_usage"]["input_tokens"], 100)
        self.assertEqual(result["_usage"]["output_tokens"], 20)
        self.assertAlmostEqual(result["_usage"]["cost"], 0.01755)

    @patch.dict(
        "dataController.selector.candidate_selector.os.environ",
        {},
        clear=True,
    )
    def test_requires_openai_api_key(self):
        with self.assertRaisesRegex(RuntimeError, "OPEN_AI_API_KEY_SELECT_API"):
            _call_openai_select_candidate([])


if __name__ == "__main__":
    unittest.main()
