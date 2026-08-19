import unittest
from unittest.mock import AsyncMock, patch

from dataController.selector.candidate_selector import prioritize_candidates
from dataController.selector.detect_api_auto import (
    build_candidate_evidence,
    find_api,
)


class CandidateEvidenceTests(unittest.TestCase):
    def test_query_values_userinfo_and_fragment_are_not_persisted(self):
        evidence = build_candidate_evidence(
            [
                {
                    "api_index": 3,
                    "api_url": (
                        "https://user:secret@example.com/notices"
                        "?token=private&page=2#content"
                    ),
                    "score": 42,
                    "features": {"has_repeated_records": True},
                    "validation_reason": (
                        "request failed: "
                        "https://user:secret@example.com/notices"
                        "?token=private&page=2#content"
                    ),
                }
            ],
            selected_candidate_index=3,
        )

        self.assertEqual(len(evidence), 1)
        item = evidence[0]
        self.assertEqual(
            item["endpoint"],
            "https://example.com/notices?page=&token=",
        )
        self.assertNotIn("private", item["endpoint"])
        self.assertNotIn("secret", item["endpoint"])
        self.assertNotIn("content", item["endpoint"])
        self.assertNotIn("private", item["validation_reason"])
        self.assertNotIn("secret", item["validation_reason"])
        self.assertTrue(item["selected"])
        self.assertEqual(len(item["url_hash"]), 64)


class CandidateSelectionTelemetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_rule_selection_carries_decision_and_reason(self):
        candidates = [
            {
                "api_index": 1,
                "api_url": "https://public.example/notices",
                "method_type": "GET",
                "source_kind": "document_html",
                "type": "document",
                "content_type": "text/html",
                "sample": "notice " * 30,
                "data_key_hits": ["title", "date"],
                "has_repeated_records": True,
                "semantic_record_count": 3,
                "title_date_pair_count": 3,
                "has_notice_terms": True,
            }
        ]

        prioritized = await prioritize_candidates(
            candidates,
            "https://public.example/notices",
        )

        self.assertEqual(prioritized[0]["selection_decision"], "accept_rule")
        self.assertEqual(prioritized[0]["selection_mode"], "rule_based")
        self.assertTrue(prioritized[0]["selection_reason"])

    async def test_no_candidates_records_a_failed_selection_run(self):
        with (
            patch(
                "dataController.selector.detect_api_auto.validate_public_url",
                return_value=type(
                    "ValidatedUrl",
                    (),
                    {"url": "https://public.example/notices"},
                )(),
            ),
            patch(
                "dataController.selector.detect_api_auto.notice_repo.select_api",
                return_value=None,
            ),
            patch(
                "dataController.selector.detect_api_auto.notice_repo.select_site_id",
                return_value=7,
            ),
            patch(
                "dataController.selector.detect_api_auto.collect_candidates",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "dataController.selector.detect_api_auto.notice_repo.create_crawl_run",
                return_value=51,
            ) as create_run,
            patch(
                "dataController.selector.detect_api_auto.notice_repo.finish_crawl_run",
            ) as finish_run,
            patch(
                "dataController.selector.detect_api_auto.notice_repo.update_site_crawl_state",
            ),
        ):
            result = await find_api("https://public.example/notices")

        self.assertIsNone(result)
        create_kwargs = create_run.call_args.kwargs
        self.assertEqual(
            create_kwargs["selection_decision"],
            "reject_or_observe_more",
        )
        self.assertEqual(create_kwargs["candidate_count"], 0)
        self.assertEqual(create_kwargs["candidate_evidence"], [])
        finish_run.assert_called_once_with(
            51,
            status="failed",
            error_code="NO_CANDIDATES",
            error_message="수집된 API 후보가 없습니다.",
        )


if __name__ == "__main__":
    unittest.main()
