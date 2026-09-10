"""Compatibility facade for bounded source structure sampling."""

from dataController.scraper.views.structure_sampler import (
    SOURCE_VIEW_STRATEGIES,
    StructureSample,
    sample_html_structure,
    sample_json_structure,
    sample_source_structure,
)
from dataController.scraper.views.evidence_sanitizer import (
    sanitize_html_evidence_fragment,
    sanitize_json_evidence_value,
)

__all__ = [
    "SOURCE_VIEW_STRATEGIES",
    "StructureSample",
    "sample_html_structure",
    "sample_json_structure",
    "sample_source_structure",
    "sanitize_html_evidence_fragment",
    "sanitize_json_evidence_value",
]
