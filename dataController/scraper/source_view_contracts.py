"""Compatibility facade for the legacy source-view contracts path."""

from dataController.scraper.views.contracts import (
    SourceEvidenceProfile,
    SourceViewAttempt,
    SourceViewState,
    SourceViewValidation,
)

__all__ = [
    "SourceEvidenceProfile",
    "SourceViewAttempt",
    "SourceViewState",
    "SourceViewValidation",
]
