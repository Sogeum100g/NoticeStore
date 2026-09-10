"""Fail-closed orchestration for proposing and approving a new active rule."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dataController.scraper.extraction.rules.executor import (
    RuleExecutionResult,
    execute_extractor_rule,
)
from dataController.scraper.agent.client import (
    evaluate_extraction_result,
    generate_extractor_rule,
    select_source_view,
)
from dataController.scraper.agent.contracts import (
    ResultEvaluationV2,
    SourceViewCandidateV1,
    SourceViewGroupEvidenceV1,
    SourceViewSelectionRequestV1,
)
from dataController.scraper.extraction.rules.contracts import ExtractorRuleV1
from dataController.scraper.extraction.rules.hard_gate import (
    HardGateResult,
    build_result_evaluation_request,
    validate_rule_execution,
)
from dataController.scraper.views.structure_sampler import (
    StructureSample,
    sample_source_structure,
)
from dataController.scraper.views.evidence_profiler import diagnose_source_view
from dataController.scraper.views.contracts import (
    SourceViewAttempt,
    SourceViewState,
)


MAX_SOURCE_VIEW_ATTEMPTS = 3
_SOURCE_VIEW_STRATEGY_PRIORITY = {
    "default_structure_sampler": 0,
    "navigation_preserving": 1,
    "table_region_preserving": 2,
}


def _source_view_quality(
    sample: StructureSample,
    attempt: SourceViewAttempt,
) -> tuple[int, float, bool]:
    return (
        len(attempt.validation.reason_codes),
        sum(attempt.validation.evidence_loss.values()),
        sample.truncated,
    )


def _view_selection_candidate(
    sample: StructureSample,
    attempt: SourceViewAttempt,
) -> SourceViewCandidateV1:
    groups = []
    for index, group in enumerate(sample.payload.get("record_groups") or []):
        groups.append(
            SourceViewGroupEvidenceV1(
                evidence_id=str(
                    group.get("evidence_id") or f"view-group-{index}"
                ),
                region_role=group.get("region_role"),
                selector_or_path=(
                    group.get("suggested_selector")
                    or group.get("records_path")
                ),
                detected_record_count=int(
                    group.get("detected_record_count") or 0
                ),
            )
        )
    metrics = sample.metrics()
    return SourceViewCandidateV1(
        strategy=sample.strategy,
        payload_hash=attempt.payload_hash,
        validation_state=attempt.validation.state.value,
        reason_codes=attempt.validation.reason_codes,
        evidence_loss=attempt.validation.evidence_loss,
        payload_chars=int(metrics["payload_chars"]),
        truncated=sample.truncated,
        groups=groups,
    )


@dataclass(frozen=True)
class RuleActivationResult:
    status: str
    rule_origin: str
    rule: Optional[ExtractorRuleV1]
    approved_notices: List[Dict[str, Optional[str]]]
    execution: Optional[RuleExecutionResult]
    hard_gate: Optional[HardGateResult]
    evaluation: Optional[ResultEvaluationV2]
    usage_by_stage: List[Dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    failure_code: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    @property
    def approved(self) -> bool:
        return self.status == "approved"


async def activate_candidate_rule(
    raw_data: Any,
    *,
    source_type: str,
    target_url: str,
    source_url: str,
    semantic_record_count: int = 0,
    baseline_notices: Optional[List[Dict[str, Optional[str]]]] = None,
    rule_based_candidate: Optional[ExtractorRuleV1] = None,
) -> RuleActivationResult:
    """Return notices only after hard gates and mandatory semantic approval.

    This function does not write to the database. Its approved output is the
    boundary a persistence transaction may consume later.
    """
    usage_by_stage: List[Dict[str, Any]] = []
    sample: Optional[StructureSample] = None
    source_view_attempt: Optional[SourceViewAttempt] = None
    source_view_attempts: List[SourceViewAttempt] = []
    source_view_selection_mode = "not_required"
    generation_failure_code = "RULE_GENERATION_FAILED"
    generated = rule_based_candidate is None
    rule_origin = "rule_extractor" if generated else "rule_based"

    async def generated_rule() -> ExtractorRuleV1:
        nonlocal sample, source_view_attempt, generation_failure_code
        nonlocal source_view_selection_mode
        if sample is None:
            pending_strategies = ["default_structure_sampler"]
            seen_strategies = set(pending_strategies)
            seen_payload_hashes: set[str] = set()
            sampled_candidates: List[
                tuple[StructureSample, SourceViewAttempt]
            ] = []
            while (
                pending_strategies
                and len(source_view_attempts) < MAX_SOURCE_VIEW_ATTEMPTS
            ):
                strategy = pending_strategies.pop(0)
                try:
                    candidate_sample = sample_source_structure(
                        raw_data,
                        source_type=source_type,
                        strategy=strategy,
                    )
                except Exception as exc:
                    usage_by_stage.append(
                        {
                            "stage": "structure_sampler",
                            "provider": "local",
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "cost": 0.0,
                            "strategy": strategy,
                            "status": "failed",
                            "error_type": type(exc).__name__,
                            "error": str(exc)[:500],
                            "selected": False,
                        }
                    )
                    if not sampled_candidates:
                        generation_failure_code = "STRUCTURE_SAMPLE_FAILED"
                        raise
                    continue
                candidate_attempt = diagnose_source_view(
                    raw_data,
                    candidate_sample,
                    source_type=source_type,
                    strategy=strategy,
                )
                if candidate_attempt.payload_hash in seen_payload_hashes:
                    continue
                seen_payload_hashes.add(candidate_attempt.payload_hash)
                source_view_attempts.append(candidate_attempt)
                sampled_candidates.append(
                    (candidate_sample, candidate_attempt)
                )
                usage_by_stage.append(
                    {
                        "stage": "structure_sampler",
                        "provider": "local",
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost": 0.0,
                        "metrics": candidate_sample.metrics(),
                        "source_view": candidate_attempt.as_dict(),
                    }
                )
                if (
                    candidate_attempt.validation.state == SourceViewState.READY
                    and not pending_strategies
                ):
                    break
                if (
                    source_type == "html"
                    and "NAVIGATION_EVIDENCE_LOST"
                    in candidate_attempt.validation.reason_codes
                    and "navigation_preserving" not in seen_strategies
                ):
                    pending_strategies.append("navigation_preserving")
                    seen_strategies.add("navigation_preserving")
                if (
                    source_type == "html"
                    and "RECORD_EVIDENCE_LOST"
                    in candidate_attempt.validation.reason_codes
                    and candidate_attempt.raw_evidence.table_count > 0
                    and "table_region_preserving" not in seen_strategies
                ):
                    pending_strategies.append("table_region_preserving")
                    seen_strategies.add("table_region_preserving")

            if not sampled_candidates:
                generation_failure_code = "STRUCTURE_SAMPLE_EMPTY"
                raise ValueError("사용 가능한 Source View가 없습니다.")
            best_quality = min(
                _source_view_quality(candidate_sample, candidate_attempt)
                for candidate_sample, candidate_attempt in sampled_candidates
            )
            tied = [
                (candidate_sample, candidate_attempt)
                for candidate_sample, candidate_attempt in sampled_candidates
                if _source_view_quality(candidate_sample, candidate_attempt)
                == best_quality
            ]
            selected = min(
                tied,
                key=lambda item: _SOURCE_VIEW_STRATEGY_PRIORITY[
                    item[0].strategy
                ],
            )
            if len(tied) > 1:
                request = SourceViewSelectionRequestV1(
                    version=1,
                    candidates=[
                        _view_selection_candidate(
                            candidate_sample,
                            candidate_attempt,
                        )
                        for candidate_sample, candidate_attempt in tied
                    ],
                )
                try:
                    selection_response = await select_source_view(request)
                    usage_by_stage.append(
                        {
                            "stage": selection_response.stage,
                            **selection_response.usage,
                            "selected_strategy": (
                                selection_response.value.strategy
                            ),
                            "selected_payload_hash": (
                                selection_response.value.payload_hash
                            ),
                        }
                    )
                    selected = next(
                        item
                        for item in tied
                        if item[0].strategy
                        == selection_response.value.strategy
                        and item[1].payload_hash
                        == selection_response.value.payload_hash
                    )
                    source_view_selection_mode = "ai_tiebreak"
                except Exception as exc:
                    usage_by_stage.append(
                        {
                            "stage": "view_selector",
                            "provider": "local",
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "cost": 0.0,
                            "status": "failed",
                            "error_type": type(exc).__name__,
                            "error": str(exc)[:500],
                        }
                    )
                    source_view_selection_mode = "deterministic_fallback"
            else:
                source_view_selection_mode = "deterministic"
            sample, source_view_attempt = selected
            for stage in usage_by_stage:
                source_view = stage.get("source_view") or {}
                if source_view:
                    stage["selected"] = (
                        source_view.get("payload_hash")
                        == source_view_attempt.payload_hash
                    )
            metrics = sample.metrics()
            if not metrics["sampled_record_count"] and not metrics["fallback_present"]:
                generation_failure_code = "STRUCTURE_SAMPLE_EMPTY"
                raise ValueError("구조 샘플에 레코드와 fallback이 없습니다.")
            if source_view_attempt.validation.state == SourceViewState.REPARSE_REQUIRED:
                reason_codes = set(
                    source_view_attempt.validation.reason_codes
                )
                if "VIEW_TRUNCATED" in reason_codes:
                    generation_failure_code = "SOURCE_TRUNCATED"
                    raise ValueError(
                        "크기 제한으로 Source View 핵심 증거가 손실됐습니다."
                    )
                if "EMBEDDED_DATA_NOT_EXPANDED" in reason_codes:
                    generation_failure_code = "UNSUPPORTED_SOURCE_STRUCTURE"
                    raise ValueError(
                        "지원되는 hydration 형식에서 반복 레코드를 복원하지 "
                        "못했습니다."
                    )
                generation_failure_code = "VIEW_ATTEMPTS_EXHAUSTED"
                raise ValueError(
                    "허용된 Source View 복구 시도를 모두 사용했지만 핵심 "
                    "증거가 보존되지 않았습니다."
                )
        generation_failure_code = "RULE_GENERATION_FAILED"
        response = await generate_extractor_rule(
            target_url=target_url,
            source_url=source_url,
            sample=sample,
        )
        usage_by_stage.append(
            {"stage": response.stage, **response.usage}
        )
        return response.value

    def activation_diagnostics(
        *,
        hard_gate_reason_codes: Optional[List[str]] = None,
        semantic_diagnostic_codes: Optional[List[str]] = None,
        failed: bool = False,
    ) -> Dict[str, Any]:
        diagnostics: Dict[str, Any] = {
            "hard_gate_reason_codes": list(hard_gate_reason_codes or []),
            "semantic_diagnostic_codes": list(
                semantic_diagnostic_codes or []
            ),
            "structure_sample": sample.metrics() if sample else None,
            "source_view_attempt": (
                source_view_attempt.as_dict() if source_view_attempt else None
            ),
            "source_view_attempts": [
                attempt.as_dict() for attempt in source_view_attempts
            ],
            "source_view_recovered": bool(
                len(source_view_attempts) > 1
                and source_view_attempt is not None
                and source_view_attempt.validation.state == SourceViewState.READY
            ),
            "source_view_selection_mode": source_view_selection_mode,
        }
        if failed:
            if generation_failure_code.startswith("STRUCTURE_SAMPLE"):
                recovery_state = SourceViewState.REPARSE_REQUIRED
            elif (
                source_view_attempt is not None
                and source_view_attempt.validation.state
                == SourceViewState.REPARSE_REQUIRED
            ):
                recovery_state = SourceViewState.REPARSE_REQUIRED
            else:
                recovery_state = SourceViewState.RULE_RETRY_REQUIRED
            diagnostics["recovery_state"] = recovery_state.value
        return diagnostics

    try:
        candidate = rule_based_candidate or await generated_rule()
    except Exception as exc:
        failure_prefix = (
            "Source View 준비 실패"
            if generation_failure_code
            in {
                "STRUCTURE_SAMPLE_FAILED",
                "STRUCTURE_SAMPLE_EMPTY",
                "SOURCE_TRUNCATED",
                "UNSUPPORTED_SOURCE_STRUCTURE",
                "VIEW_ATTEMPTS_EXHAUSTED",
            }
            else "Rule Extractor 호출 또는 응답 검증 실패"
        )
        return RuleActivationResult(
            status="failed",
            rule_origin=rule_origin,
            rule=None,
            approved_notices=[],
            execution=None,
            hard_gate=None,
            evaluation=None,
            usage_by_stage=usage_by_stage,
            reason=f"{failure_prefix}: {exc}",
            failure_code=generation_failure_code,
            diagnostics=activation_diagnostics(failed=True),
        )

    # A rejected rule-based candidate gets one AI regeneration. An AI rule is
    # never regenerated indefinitely inside one activation attempt.
    for _attempt in range(2):
        execution = execute_extractor_rule(
            raw_data,
            rule=candidate,
            base_url=(source_url if source_type == "html" else target_url),
        )
        hard_gate = validate_rule_execution(
            execution,
            rule=candidate,
            semantic_record_count=semantic_record_count,
            baseline_notices=baseline_notices,
        )

        if hard_gate.passed:
            request = build_result_evaluation_request(
                target_url=target_url,
                source_url=source_url,
                rule=candidate,
                execution=execution,
                hard_gate=hard_gate,
            )
            try:
                evaluation_response = await evaluate_extraction_result(request)
                usage_by_stage.append(
                    {
                        "stage": evaluation_response.stage,
                        **evaluation_response.usage,
                    }
                )
                evaluation = evaluation_response.value
            except Exception as exc:
                return RuleActivationResult(
                    status="failed",
                    rule_origin=rule_origin,
                    rule=candidate,
                    approved_notices=[],
                    execution=execution,
                    hard_gate=hard_gate,
                    evaluation=None,
                    usage_by_stage=usage_by_stage,
                    reason=f"Result Evaluator 호출 또는 응답 검증 실패: {exc}",
                    failure_code="SEMANTIC_EVALUATION_FAILED",
                    diagnostics=activation_diagnostics(
                        hard_gate_reason_codes=hard_gate.reason_codes,
                        semantic_diagnostic_codes=(
                            hard_gate.semantic_diagnostic_codes
                        ),
                    ),
                )

            if evaluation.decision == "pass":
                return RuleActivationResult(
                    status="approved",
                    rule_origin=rule_origin,
                    rule=candidate,
                    approved_notices=execution.notices,
                    execution=execution,
                    hard_gate=hard_gate,
                    evaluation=evaluation,
                    usage_by_stage=usage_by_stage,
                    reason=evaluation.reason,
                    diagnostics=activation_diagnostics(
                        hard_gate_reason_codes=hard_gate.reason_codes,
                        semantic_diagnostic_codes=(
                            hard_gate.semantic_diagnostic_codes
                        ),
                    ),
                )
        else:
            evaluation = None

        if generated:
            failure_reason = (
                evaluation.reason
                if evaluation is not None
                else hard_gate.reason
            )
            return RuleActivationResult(
                status="rejected",
                rule_origin=rule_origin,
                rule=candidate,
                approved_notices=[],
                execution=execution,
                hard_gate=hard_gate,
                evaluation=evaluation,
                usage_by_stage=usage_by_stage,
                reason=failure_reason,
                failure_code=(
                    "RULE_EXECUTION_FAILED"
                    if execution.status == "failed"
                    else "RULE_HARD_GATE_REJECTED"
                    if not hard_gate.passed
                    else "SEMANTIC_EVALUATION_REJECTED"
                ),
                diagnostics=activation_diagnostics(
                    hard_gate_reason_codes=hard_gate.reason_codes,
                    semantic_diagnostic_codes=(
                        hard_gate.semantic_diagnostic_codes
                    ),
                    failed=True,
                ),
            )

        try:
            candidate = await generated_rule()
        except Exception as exc:
            return RuleActivationResult(
                status="failed",
                rule_origin="rule_extractor",
                rule=None,
                approved_notices=[],
                execution=execution,
                hard_gate=hard_gate,
                evaluation=evaluation,
                usage_by_stage=usage_by_stage,
                reason=f"Rule-based 후보 거부 후 규칙 재생성 실패: {exc}",
                failure_code=generation_failure_code,
                diagnostics=activation_diagnostics(
                    hard_gate_reason_codes=hard_gate.reason_codes,
                    semantic_diagnostic_codes=(
                        hard_gate.semantic_diagnostic_codes
                    ),
                    failed=True,
                ),
            )
        generated = True
        rule_origin = "rule_extractor"

    return RuleActivationResult(
        status="failed",
        rule_origin=rule_origin,
        rule=candidate,
        approved_notices=[],
        execution=execution,
        hard_gate=hard_gate,
        evaluation=evaluation,
        usage_by_stage=usage_by_stage,
        reason="규칙 활성화 시도 횟수를 초과했습니다.",
        failure_code="RULE_ACTIVATION_ATTEMPTS_EXHAUSTED",
        diagnostics=activation_diagnostics(
            hard_gate_reason_codes=hard_gate.reason_codes,
            semantic_diagnostic_codes=(
                hard_gate.semantic_diagnostic_codes
            ),
            failed=True,
        ),
    )
