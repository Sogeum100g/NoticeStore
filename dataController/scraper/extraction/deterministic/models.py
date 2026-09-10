"""Result model shared by deterministic extractors and pipeline code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

@dataclass
class ExtractionResult:
    status: str
    notices: List[Dict[str, Any]]
    extractor_config: Optional[Dict[str, Any]]
    schema_hash: Optional[str]
    confidence: float
    intermediate: Optional[Dict[str, Any]]
    error: Optional[str] = None

    def as_processing_result(self, site_id: Optional[int] = None) -> Dict[str, Any]:
        result = {
            "status": "success" if self.status != "failed" else "error",
            "site_id": site_id,
            "notices": self.notices,
        }
        if self.error:
            result["error_msg"] = self.error
        return result


__all__ = ["ExtractionResult"]
