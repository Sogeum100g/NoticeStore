"""Compatibility facade for the crawl pipeline runner."""

import sys

from dataController.scraper.pipeline import runner as _implementation
from dataController.scraper.pipeline.runner import (
    _complete_structured_processing,
    run_full_scrape,
)

__all__ = ["run_full_scrape"]

# Legacy patch paths now resolve to the canonical implementation module.
_implementation.__all__ = __all__
sys.modules[__name__] = _implementation
