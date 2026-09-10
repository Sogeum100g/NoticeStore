"""Aggregation of bounded extraction-agent telemetry."""

from __future__ import annotations

from typing import Any, Dict


def agent_run_telemetry(api: Dict[str, Any]) -> Dict[str, Any]:
    stages = []
    source_view_metrics = api.get("_source_view_metrics")
    if source_view_metrics:
        stages.append(
            {
                "stage": "source_view",
                "provider": "local",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
                "metrics": source_view_metrics,
            }
        )
    coverage_diagnostics = api.get("_coverage_diagnostics")
    if coverage_diagnostics:
        stages.append(
            {
                "stage": "coverage_diagnostics",
                "provider": "local",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
                **coverage_diagnostics,
            }
        )
    selector_usage = api.get("_llm_usage") or {}
    if api.get("_llm_used"):
        stages.append({"stage": "api_selector", **selector_usage})
    stages.extend(api.get("_extraction_agent_usage") or [])

    activation = api.get("_rule_activation") or {}
    return {
        "stages": stages,
        "llm_used": any(
            item.get("provider") != "local"
            and item.get("stage") != "structure_sampler"
            for item in stages
        ),
        "input_tokens": sum(int(item.get("input_tokens") or 0) for item in stages),
        "output_tokens": sum(int(item.get("output_tokens") or 0) for item in stages),
        "cost": sum(float(item.get("cost") or 0.0) for item in stages),
        "activation_status": activation.get("status"),
        "activation_reason": activation.get("reason"),
        "evaluator_decision": activation.get("evaluator_decision"),
        "evaluator_confidence": activation.get("evaluator_confidence"),
    }


__all__ = ["agent_run_telemetry"]
