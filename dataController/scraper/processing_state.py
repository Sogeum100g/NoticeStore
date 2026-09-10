"""Compatibility facade for the legacy processing-state import path."""

from dataController.scraper.pipeline.processing_state import (
    classify_processing_result,
    decide_observation,
)

__all__ = ["classify_processing_result", "decide_observation"]
