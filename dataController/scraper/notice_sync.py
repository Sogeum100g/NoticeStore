"""Compatibility facade for notice synchronization."""

import sys

from dataController.scraper.persistence import notice_sync as _implementation
from dataController.scraper.persistence.notice_sync import (
    get_recent_info,
    process_notice_request,
    sync_notices_to_db,
)

__all__ = [
    "get_recent_info",
    "process_notice_request",
    "sync_notices_to_db",
]

_implementation.__all__ = __all__
sys.modules[__name__] = _implementation
