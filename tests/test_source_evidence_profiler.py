import unittest
from pathlib import Path

from dataController.scraper.source_evidence_profiler import (
    diagnose_source_view,
    profile_html_source,
    profile_json_source,
    validate_source_view,
)
from dataController.scraper.source_view_contracts import (
    SourceEvidenceProfile,
    SourceViewState,
)
from dataController.scraper.structure_sampler import StructureSample, sample_source_structure


class SourceEvidenceProfilerTests(unittest.TestCase):
    def test_gallery_title_cells_survive_sampling_without_heading_classes(self):
        raw = (Path(__file__).parent / "fixtures" / "dcinside_board.html").read_text()
        # Full pages contain unrelated headings which are intentionally not sampled.
        raw = raw.replace("<body>", "<body><header><h1>갤러리</h1><h2>사이트 메뉴</h2></header>")
        sample = sample_source_structure(raw, source_type="html")
        attempt = diagnose_source_view(raw, sample, source_type="html")
        self.assertGreater(attempt.view_evidence.title_evidence_count, 0)
        self.assertEqual(attempt.validation.state, SourceViewState.READY)

    def test_empty_title_cells_do_not_hide_real_title_loss(self):
        raw = '<ul><li><a class="post_tit" href="/1">첫 게시글</a></li><li><a class="post_tit" href="/2">둘째 게시글</a></li></ul>'
        view = '<ul><li><a class="post_tit" href="/1"></a>2026-09-06</li><li><a class="post_tit" href="/2"></a>2026-09-05</li></ul>'
        validation = validate_source_view(profile_html_source(raw), profile_html_source(view))
        self.assertIn("FIELD_EVIDENCE_LOST", validation.reason_codes)

    def test_normal_html_sample_preserves_record_and_navigation_evidence(self):
        html = """
        <main><ul class="notices">
          <li><a href="/notice/1"><h2>첫 공지</h2></a><time>2026-08-30</time></li>
          <li><a href="/notice/2"><h2>둘째 공지</h2></a><time>2026-08-29</time></li>
        </ul></main>
        """
        sample = StructureSample(
            source_type="html",
            payload={
                "record_groups": [
                    {
                        "detected_record_count": 2,
                        "records": [
                            {"html": "<li><a href='/notice/1'><h2>첫 공지</h2></a><time>2026-08-30</time></li>"},
                            {"html": "<li><a href='/notice/2'><h2>둘째 공지</h2></a><time>2026-08-29</time></li>"},
                        ],
                    }
                ],
                "fallback_html": None,
            },
            evidence_ids=set(),
            truncated=False,
        )

        attempt = diagnose_source_view(html, sample, source_type="html")

        self.assertEqual(attempt.validation.state, SourceViewState.READY)
        self.assertEqual(attempt.view_evidence.record_candidate_count, 2)
        self.assertGreaterEqual(attempt.view_evidence.navigation_evidence_count, 2)

    def test_navigation_loss_requests_reparse(self):
        raw = SourceEvidenceProfile(
            source_type="html",
            record_candidate_count=20,
            navigation_evidence_count=20,
            title_evidence_count=20,
        )
        view = SourceEvidenceProfile(
            source_type="html",
            record_candidate_count=20,
            title_evidence_count=20,
        )

        validation = validate_source_view(raw, view)

        self.assertEqual(validation.state, SourceViewState.REPARSE_REQUIRED)
        self.assertIn("NAVIGATION_EVIDENCE_LOST", validation.reason_codes)
        self.assertEqual(validation.evidence_loss["navigation"], 1.0)

    def test_truncated_view_with_preserved_evidence_remains_usable(self):
        validation = validate_source_view(
            SourceEvidenceProfile(source_type="html", record_candidate_count=10),
            SourceEvidenceProfile(
                source_type="html",
                record_candidate_count=10,
                truncated=True,
            ),
        )

        self.assertEqual(validation.state, SourceViewState.READY)
        self.assertNotIn("VIEW_TRUNCATED", validation.reason_codes)

    def test_truncated_view_with_severe_evidence_loss_requests_reparse(self):
        validation = validate_source_view(
            SourceEvidenceProfile(
                source_type="html",
                record_candidate_count=10,
                navigation_evidence_count=10,
            ),
            SourceEvidenceProfile(
                source_type="html",
                record_candidate_count=2,
                navigation_evidence_count=1,
                truncated=True,
            ),
        )

        self.assertEqual(validation.state, SourceViewState.REPARSE_REQUIRED)
        self.assertIn("VIEW_TRUNCATED", validation.reason_codes)

    def test_embedded_data_without_records_is_reported(self):
        validation = validate_source_view(
            SourceEvidenceProfile(source_type="html", embedded_data_count=2),
            SourceEvidenceProfile(source_type="html"),
        )

        self.assertIn("EMBEDDED_DATA_NOT_EXPANDED", validation.reason_codes)

    def test_html_and_json_profiles_capture_bounded_contract_evidence(self):
        html_profile = profile_html_source(
            "<script id='__NEXT_DATA__'>{}</script>"
            "<ul><li><a data-id='1' href='javascript:'>첫 공지</a></li>"
            "<li><a data-id='2' href='javascript:'>둘째 공지</a></li></ul>"
        )
        json_profile = profile_json_source(
            {
                "items": [
                    {"title": "첫 공지", "publishedAt": "2026-08-30", "id": 1},
                    {"title": "둘째 공지", "publishedAt": "2026-08-29", "id": 2},
                ]
            }
        )

        self.assertEqual(html_profile.record_candidate_count, 2)
        self.assertGreaterEqual(html_profile.navigation_evidence_count, 2)
        self.assertGreaterEqual(html_profile.embedded_data_count, 1)
        self.assertEqual(json_profile.record_candidate_count, 2)
        self.assertGreaterEqual(json_profile.title_evidence_count, 1)
        self.assertGreaterEqual(json_profile.date_evidence_count, 1)

    def test_sampler_evidence_ids_are_not_counted_as_navigation(self):
        profile = profile_html_source(
            "<ul><li><a data-evidence-id='record-1'>첫 공지</a></li>"
            "<li><a data-evidence-id='record-2'>둘째 공지</a></li></ul>"
        )

        self.assertEqual(profile.navigation_evidence_count, 0)
        self.assertEqual(profile.data_attribute_count, 0)


if __name__ == "__main__":
    unittest.main()
