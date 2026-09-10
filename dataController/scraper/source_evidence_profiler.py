"""Compatibility facade for source-view evidence profiling."""

from dataController.scraper.views.evidence_profiler import (
    SourceViewValidation,
    diagnose_source_view,
    profile_html_source,
    profile_json_source,
    profile_source,
    profile_structure_sample,
    validate_source_view,
)

__all__ = [
    "SourceViewValidation",
    "diagnose_source_view",
    "profile_html_source",
    "profile_json_source",
    "profile_source",
    "profile_structure_sample",
    "validate_source_view",
]
