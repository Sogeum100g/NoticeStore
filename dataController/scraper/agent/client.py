"""Structured AI calls for rule generation and one-time result evaluation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Dict, Generic, Literal, Type, TypeVar

import yaml
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

from dataController.scraper.agent.contracts import (
    ResultEvaluationV2,
    SourceViewSelectionRequestV1,
    SourceViewSelectionV1,
)
from dataController.scraper.extraction.contracts import ResultEvaluationRequestV2
from dataController.scraper.extraction.rules.contracts import ExtractorRuleV1
from dataController.scraper.views.structure_sampler import StructureSample


# Keep the established logger name so dashboards and legacy assertions do not
# split telemetry merely because the implementation moved packages.
logger = logging.getLogger("dataController.scraper.extraction_agent_client")
load_dotenv()

_CONFIG_PATH = files("dataController").joinpath("prompt_data.yaml")
with _CONFIG_PATH.open("r", encoding="utf-8") as _prompt_file:
    _PROMPTS = yaml.safe_load(_prompt_file)["prompts"]

StageName = Literal["view_selector", "rule_extractor", "result_evaluator"]
ModelT = TypeVar("ModelT", bound=BaseModel)
_SUPPORTED_PROVIDERS = {"openai", "gemini"}
_USD_TO_KRW = 1350
_OPENAI_INPUT_USD_PER_MILLION = 0.40
_OPENAI_OUTPUT_USD_PER_MILLION = 1.60
_GEMINI_INPUT_USD_PER_MILLION = 0.30
_GEMINI_OUTPUT_USD_PER_MILLION = 2.50


@dataclass(frozen=True)
class StructuredAgentResponse(Generic[ModelT]):
    stage: StageName
    value: ModelT
    usage: Dict[str, Any]


def _get_provider() -> str:
    provider = os.getenv("LLM_PROVIDER", "openai").strip().casefold()
    if provider == "google":
        provider = "gemini"
    if provider not in _SUPPORTED_PROVIDERS:
        raise RuntimeError(f"지원하지 않는 LLM_PROVIDER입니다: {provider!r}")
    return provider


def _stage_environment_suffix(stage: StageName) -> str:
    return stage.upper()


def _get_api_key(provider: str, stage: StageName) -> str:
    suffix = _stage_environment_suffix(stage)
    if provider == "openai":
        key = (
            os.getenv(f"OPEN_AI_API_KEY_{suffix}")
            or os.getenv("OPEN_AI_API_KEY_SELECT_API")
            or os.getenv("OPENAI_API_KEY")
        )
    else:
        key = (
            os.getenv(f"GEMINI_API_KEY_{suffix}")
            or os.getenv("GEMINI_API_KEY_SELECT_API")
            or os.getenv("GEMINI_API_KEY")
        )
    if not key:
        raise RuntimeError(f"{provider}/{stage} API 키가 비어 있습니다.")
    return key


def _get_model(provider: str, stage: StageName) -> str:
    suffix = _stage_environment_suffix(stage)
    if provider == "openai":
        model = os.getenv(f"OPENAI_{suffix}_MODEL") or os.getenv("OPENAI_MODEL")
        prefix = "openai/"
    else:
        model = os.getenv(f"GEMINI_{suffix}_MODEL") or os.getenv("GEMINI_MODEL")
        prefix = "models/"
    if not model:
        raise RuntimeError(f"{provider}/{stage} 모델 환경 변수가 비어 있습니다.")
    return model.removeprefix(prefix)


def _estimate_cost_krw(
    *,
    provider: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    if provider == "openai":
        input_price = _OPENAI_INPUT_USD_PER_MILLION
        output_price = _OPENAI_OUTPUT_USD_PER_MILLION
    else:
        input_price = _GEMINI_INPUT_USD_PER_MILLION
        output_price = _GEMINI_OUTPUT_USD_PER_MILLION
    return (
        (input_tokens / 1_000_000) * input_price
        + (output_tokens / 1_000_000) * output_price
    ) * _USD_TO_KRW


def _log_structured_call_usage(
    *,
    stage: StageName,
    usage: Dict[str, Any],
) -> None:
    """Log the billable usage captured for one completed agent API call."""
    thought_tokens = int(usage.get("thought_tokens") or 0)
    logger.info(
        "📊 [%s] %s API 호출 완료 | provider=%s | "
        "tokens=(in:%d / out:%d / thought:%d) | 예상 비용=₩%.4f",
        usage.get("model") or "unknown",
        stage,
        usage.get("provider") or "unknown",
        int(usage.get("input_tokens") or 0),
        int(usage.get("output_tokens") or 0),
        thought_tokens,
        float(usage.get("cost") or 0.0),
    )


def _create_gemini_client(api_key: str) -> Any:
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Gemini 사용에는 google-genai 패키지가 필요합니다.") from exc
    return genai.Client(api_key=api_key)


def _call_openai_structured(
    *,
    stage: StageName,
    prompt: str,
    response_model: Type[ModelT],
) -> StructuredAgentResponse[ModelT]:
    provider = "openai"
    api_key = _get_api_key(provider, stage)
    model = _get_model(provider, stage)
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.parse(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format=response_model,
    )
    usage = response.usage
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    usage_data = {
        "provider": provider,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost": _estimate_cost_krw(
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
    }
    _log_structured_call_usage(stage=stage, usage=usage_data)

    parsed = response.choices[0].message.parsed if response.choices else None
    if parsed is None:
        raise ValueError(f"OpenAI {stage} 구조화 응답이 비어 있습니다.")

    return StructuredAgentResponse(
        stage=stage,
        value=parsed,
        usage=usage_data,
    )


def _call_gemini_structured(
    *,
    stage: StageName,
    prompt: str,
    response_model: Type[ModelT],
) -> StructuredAgentResponse[ModelT]:
    provider = "gemini"
    api_key = _get_api_key(provider, stage)
    model = _get_model(provider, stage)
    client = _create_gemini_client(api_key)
    interaction = client.interactions.create(
        model=model,
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": response_model.model_json_schema(),
        },
    )
    usage = getattr(interaction, "usage", None)
    input_tokens = int(getattr(usage, "total_input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "total_output_tokens", 0) or 0)
    thought_tokens = int(getattr(usage, "total_thought_tokens", 0) or 0)
    usage_data = {
        "provider": provider,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "thought_tokens": thought_tokens,
        "cost": _estimate_cost_krw(
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens + thought_tokens,
        ),
    }
    _log_structured_call_usage(stage=stage, usage=usage_data)

    output_text = getattr(interaction, "output_text", None)
    if not output_text:
        raise ValueError(f"Gemini {stage} 구조화 응답이 비어 있습니다.")
    parsed = response_model.model_validate_json(output_text)

    return StructuredAgentResponse(
        stage=stage,
        value=parsed,
        usage=usage_data,
    )


def _call_structured(
    *,
    stage: StageName,
    prompt: str,
    response_model: Type[ModelT],
) -> StructuredAgentResponse[ModelT]:
    provider = _get_provider()
    if provider == "openai":
        response = _call_openai_structured(
            stage=stage,
            prompt=prompt,
            response_model=response_model,
        )
    else:
        response = _call_gemini_structured(
            stage=stage,
            prompt=prompt,
            response_model=response_model,
        )
    return response


def generate_extractor_rule_sync(
    *,
    target_url: str,
    source_url: str,
    sample: StructureSample,
) -> StructuredAgentResponse[ExtractorRuleV1]:
    context = json.dumps(
        {
            "target_url": target_url,
            "source_url": source_url,
            "structure_sample": sample.payload,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    prompt = _PROMPTS["rule_extractor"].format(context=context)
    response = _call_structured(
        stage="rule_extractor",
        prompt=prompt,
        response_model=ExtractorRuleV1,
    )
    if response.value.source_type != sample.source_type:
        raise ValueError("생성 규칙의 source_type이 입력 샘플과 다릅니다.")
    unknown_evidence = set(response.value.evidence_ids) - sample.evidence_ids
    if unknown_evidence:
        raise ValueError(
            "생성 규칙이 입력에 없는 evidence ID를 참조합니다: "
            + ", ".join(sorted(unknown_evidence))
        )
    return response


async def generate_extractor_rule(
    *,
    target_url: str,
    source_url: str,
    sample: StructureSample,
) -> StructuredAgentResponse[ExtractorRuleV1]:
    return await asyncio.to_thread(
        generate_extractor_rule_sync,
        target_url=target_url,
        source_url=source_url,
        sample=sample,
    )


def select_source_view_sync(
    request: SourceViewSelectionRequestV1,
) -> StructuredAgentResponse[SourceViewSelectionV1]:
    context = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    prompt = _PROMPTS["view_selector"].format(context=context)
    response = _call_structured(
        stage="view_selector",
        prompt=prompt,
        response_model=SourceViewSelectionV1,
    )
    allowed = {
        (candidate.strategy, candidate.payload_hash)
        for candidate in request.candidates
    }
    selected = (response.value.strategy, response.value.payload_hash)
    if selected not in allowed:
        raise ValueError("View Selector가 입력에 없는 후보를 선택했습니다.")
    return response


async def select_source_view(
    request: SourceViewSelectionRequestV1,
) -> StructuredAgentResponse[SourceViewSelectionV1]:
    return await asyncio.to_thread(select_source_view_sync, request)


def evaluate_extraction_result_sync(
    request: ResultEvaluationRequestV2,
) -> StructuredAgentResponse[ResultEvaluationV2]:
    context = json.dumps(
        request.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    prompt = _PROMPTS["result_evaluator"].format(context=context)
    logger.info(
        "Result Evaluator 입력 준비 | samples=%d context_chars=%d prompt_chars=%d",
        len(request.samples),
        len(context),
        len(prompt),
    )
    return _call_structured(
        stage="result_evaluator",
        prompt=prompt,
        response_model=ResultEvaluationV2,
    )


async def evaluate_extraction_result(
    request: ResultEvaluationRequestV2,
) -> StructuredAgentResponse[ResultEvaluationV2]:
    return await asyncio.to_thread(evaluate_extraction_result_sync, request)
