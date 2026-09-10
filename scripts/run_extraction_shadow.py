"""Run read-only extraction shadow comparisons against stored fixtures."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dataController.scraper.agent.shadow import compare_rule_based_shadow
from dataController.scraper.extraction.deterministic import (
    extract_notices_deterministically,
)
from dataController.scraper.agent.orchestrator import (
    activate_candidate_rule,
)
from dataController.scraper.extraction.rules.adapter import build_rule_based_candidate


FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures"
CASES = [
    {
        "name": "generic_html",
        "fixture": "notices.html",
        "content_type": "text/html",
        "base_url": "https://public.example/notices",
        "semantic_record_count": 2,
    },
    {
        "name": "generic_json",
        "fixture": "notices.json",
        "content_type": "application/json",
        "base_url": "https://public.example/notices",
        "semantic_record_count": 2,
    },
    {
        "name": "jobkorea_false_positive_regression",
        "fixture": "jobkorea_recruit.html",
        "content_type": "text/html",
        "base_url": "https://www.jobkorea.co.kr/company/1882711/recruit",
        "semantic_record_count": 3,
        "expected_titles": [
            "[넥슨컴퍼니] 2026 넥토리얼 for Game Programmer",
            "중국 사업/마케팅 담당자",
            "개발 PM (기획 담당)",
        ],
        "prohibited_titles": [
            "리스트 정렬 순서 선택",
            "채용 진행 중 직무",
            "진행중인 채용정보",
        ],
    },
    {
        "name": "dcinside_rule_extractor_boundary",
        "fixture": "dcinside_board.html",
        "content_type": "text/html",
        "base_url": "https://gall.dcinside.com/board/lists/?id=hair",
        "semantic_record_count": 3,
        "expected_titles": [
            "자주 올라오는 질문",
            "첫 번째 일반 게시글",
            "두 번째 일반 게시글",
        ],
    },
    {
        "name": "hanwha_dynamic_json",
        "fixture": "hanwha_recruit.json",
        "content_type": "application/json",
        "base_url": "https://www.hanwhain.com/portal/apply/recruit",
        "semantic_record_count": 2,
    },
]


def _raw_case_data(case):
    raw_text = (FIXTURE_DIR / case["fixture"]).read_text(encoding="utf-8")
    return json.loads(raw_text) if "json" in case["content_type"] else raw_text


def _selected_cases(names):
    return [case for case in CASES if not names or case["name"] in names]


def offline_results(names=None):
    results = []
    for case in _selected_cases(names):
        raw_data = _raw_case_data(case)
        comparison = compare_rule_based_shadow(
            raw_data,
            content_type=case["content_type"],
            base_url=case["base_url"],
            semantic_record_count=case["semantic_record_count"],
            expected_titles=case.get("expected_titles"),
            prohibited_titles=case.get("prohibited_titles"),
        )
        results.append({"name": case["name"], **comparison.as_dict()})
    return results


async def ai_activation_results(names=None):
    """Exercise real agents against fixtures without touching repositories."""
    results = []
    for case in _selected_cases(names):
        if case["name"] in {"generic_html", "generic_json"}:
            continue
        raw_data = _raw_case_data(case)
        deterministic = extract_notices_deterministically(
            raw_data,
            content_type=case["content_type"],
            base_url=case["base_url"],
        )
        candidate = build_rule_based_candidate(raw_data, deterministic)
        activation = await activate_candidate_rule(
            raw_data,
            source_type=(deterministic.extractor_config or {}).get("source_type"),
            target_url=case["base_url"],
            source_url=case["base_url"],
            semantic_record_count=case["semantic_record_count"],
            rule_based_candidate=candidate,
        )
        results.append(
            {
                "name": case["name"],
                "status": activation.status,
                "rule_origin": activation.rule_origin,
                "approved_notice_count": len(activation.approved_notices),
                "hard_gate_passed": (
                    activation.hard_gate.passed if activation.hard_gate else None
                ),
                "evaluator_decision": (
                    activation.evaluation.decision
                    if activation.evaluation
                    else None
                ),
                "evaluator_confidence": (
                    activation.evaluation.confidence
                    if activation.evaluation
                    else None
                ),
                "evaluator_reason": (
                    activation.evaluation.reason
                    if activation.evaluation
                    else None
                ),
                "reason": activation.reason,
                "usage_by_stage": activation.usage_by_stage,
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--with-ai",
        action="store_true",
        help="실제 Rule Extractor/Result Evaluator를 호출하되 DB에는 저장하지 않습니다.",
    )
    parser.add_argument(
        "--case",
        action="append",
        choices=[case["name"] for case in CASES],
        help="지정한 shadow case만 실행합니다. 여러 번 지정할 수 있습니다.",
    )
    args = parser.parse_args()

    results = (
        asyncio.run(ai_activation_results(args.case))
        if args.with_ai
        else offline_results(args.case)
    )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    if args.with_ai:
        return 1 if any(result["status"] != "approved" for result in results) else 0
    unsafe_statuses = {"legacy_failed", "expectation_failed", "parity_mismatch"}
    return 1 if any(result["status"] in unsafe_statuses for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
