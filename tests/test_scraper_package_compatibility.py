import ast
import importlib
import unittest
from pathlib import Path
from unittest.mock import patch


SCRAPER_ROOT = Path(__file__).parents[1] / "dataController" / "scraper"

COMPATIBILITY_EXPORTS = (
    (
        "dataController.scraper.notice_url_normalizer",
        "dataController.scraper.navigation.url_normalizer",
        ("canonicalize_notice_detail_url",),
    ),
    (
        "dataController.scraper.html_navigation",
        "dataController.scraper.navigation.html",
        ("resolve_html_navigation_url", "is_placeholder_navigation"),
    ),
    (
        "dataController.scraper.processing_state",
        "dataController.scraper.pipeline.processing_state",
        ("classify_processing_result", "decide_observation"),
    ),
    (
        "dataController.scraper.source_view_contracts",
        "dataController.scraper.views.contracts",
        ("SourceEvidenceProfile", "SourceViewState"),
    ),
    (
        "dataController.scraper.selector_stability",
        "dataController.scraper.views.selector_stability",
        ("find_volatile_html_ids", "selector_uses_volatile_html_id"),
    ),
    (
        "dataController.scraper.dcinside_source",
        "dataController.scraper.sites.dcinside",
        ("gallery_list_id", "preserve_list_filter"),
    ),
    (
        "dataController.scraper.page_extractors",
        "dataController.scraper.views.page_views",
        ("HtmlSourceViews", "build_html_source_views", "get_text_hash"),
    ),
    (
        "dataController.scraper.page_extractors",
        "dataController.scraper.views.embedded_data",
        ("extract_embedded_json_data", "extract_javascript_hydration_data"),
    ),
    (
        "dataController.scraper.page_extractors",
        "dataController.scraper.navigation.fetch_policy",
        ("expand_url", "is_crawling_allowed"),
    ),
    (
        "dataController.scraper.page_extractors",
        "dataController.scraper.sites.youtube",
        ("extract_yt_data", "parse_youtube_community_data"),
    ),
    (
        "dataController.scraper.structure_sampler",
        "dataController.scraper.views.structure_sampler",
        ("StructureSample", "sample_source_structure"),
    ),
    (
        "dataController.scraper.source_evidence_profiler",
        "dataController.scraper.views.evidence_profiler",
        ("SourceViewValidation", "diagnose_source_view"),
    ),
    (
        "dataController.scraper.extraction_agent_contracts",
        "dataController.scraper.extraction.rules.contracts",
        ("ExtractorRuleV1", "HtmlFieldRule", "JsonFieldRule"),
    ),
    (
        "dataController.scraper.extraction_agent_contracts",
        "dataController.scraper.agent.contracts",
        ("ResultEvaluationV2", "SourceViewSelectionV1"),
    ),
    (
        "dataController.scraper.deterministic_extractor",
        "dataController.scraper.extraction.deterministic",
        ("ExtractionResult", "extract_notices_deterministically"),
    ),
    (
        "dataController.scraper.declarative_rule_executor",
        "dataController.scraper.extraction.rules.executor",
        ("RuleExecutionResult", "execute_extractor_rule"),
    ),
    (
        "dataController.scraper.rule_candidate_adapter",
        "dataController.scraper.extraction.rules.adapter",
        ("build_rule_based_candidate",),
    ),
    (
        "dataController.scraper.rule_hard_gate",
        "dataController.scraper.extraction.rules.hard_gate",
        ("HardGateResult", "validate_rule_execution"),
    ),
    (
        "dataController.scraper.active_rule_config",
        "dataController.scraper.extraction.rules.active_config",
        ("build_active_rule_config", "execute_active_rule_config"),
    ),
    (
        "dataController.scraper.extraction_agent_client",
        "dataController.scraper.agent.client",
        ("StructuredAgentResponse", "generate_extractor_rule"),
    ),
    (
        "dataController.scraper.extraction_agent_orchestrator",
        "dataController.scraper.agent.orchestrator",
        ("RuleActivationResult", "activate_candidate_rule"),
    ),
    (
        "dataController.scraper.extraction_shadow",
        "dataController.scraper.agent.shadow",
        ("ShadowComparison", "compare_rule_based_shadow"),
    ),
    (
        "dataController.scraper.notice_sync",
        "dataController.scraper.persistence.notice_sync",
        ("sync_notices_to_db",),
    ),
    (
        "dataController.scraper.scrape_auto",
        "dataController.scraper.pipeline.runner",
        ("run_full_scrape",),
    ),
)

LEGACY_MODULE_NAMES = {
    item[0].rsplit(".", 1)[-1] for item in COMPATIBILITY_EXPORTS
} | {
    "dcinside_source",
    "page_extractors",
    "selector_stability",
    "source_evidence_profiler",
    "structure_sampler",
}


class ScraperPackageCompatibilityTests(unittest.TestCase):
    def test_legacy_exports_are_the_canonical_objects(self):
        for legacy_path, canonical_path, names in COMPATIBILITY_EXPORTS:
            with self.subTest(legacy=legacy_path, canonical=canonical_path):
                legacy = importlib.import_module(legacy_path)
                canonical = importlib.import_module(canonical_path)
                for name in names:
                    self.assertIn(name, legacy.__all__)
                    self.assertIs(getattr(legacy, name), getattr(canonical, name))

    def test_legacy_runner_patch_path_targets_canonical_module(self):
        importlib.import_module("dataController.scraper.scrape_auto")
        with patch(
            "dataController.scraper.scrape_auto.expand_url",
            return_value="https://example.test/notices",
        ) as mocked:
            canonical = importlib.import_module(
                "dataController.scraper.pipeline.runner"
            )
            self.assertIs(canonical.expand_url, mocked)

    def test_canonical_packages_do_not_import_legacy_facades(self):
        canonical_roots = {
            "agent",
            "extraction",
            "navigation",
            "persistence",
            "pipeline",
            "sites",
            "views",
        }
        violations = []
        for path in SCRAPER_ROOT.rglob("*.py"):
            relative = path.relative_to(SCRAPER_ROOT)
            if not relative.parts or relative.parts[0] not in canonical_roots:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or not node.module:
                    continue
                prefix = "dataController.scraper."
                if node.module.startswith(prefix):
                    imported_name = node.module[len(prefix):].split(".", 1)[0]
                    if imported_name in LEGACY_MODULE_NAMES:
                        violations.append((str(relative), node.lineno, node.module))
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
