"""Read-only live verification for representative notice sources."""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict

import requests

from dataController.security.url_safety import safe_request
from dataController.scraper.extraction.rules.executor import execute_extractor_rule
from dataController.scraper.extraction.deterministic import (
    extract_notices_deterministically,
)
from dataController.scraper.extraction.rules.adapter import build_rule_based_candidate
from dataController.scraper.extraction.rules.hard_gate import validate_rule_execution
from dataController.scraper.views.structure_sampler import sample_source_structure
from dataController.selector.candidate_analyzer import analyze_candidate_body


SOURCES = {
    "kakao": {
        "target_url": "https://careers.kakao.com/jobs",
        "source_url": (
            "https://careers.kakao.com/public/api/job-list"
            "?skillSet=&part=TECHNOLOGY&company=KAKAO&employeeType=&page=1"
        ),
    },
    "onoffmix": {
        "target_url": "https://www.onoffmix.com/event/main",
    },
    "lostark": {
        "target_url": "https://lostark.game.onstove.com/News/Notice/List",
    },
    "valorant": {
        "target_url": "https://playvalorant.com/ko-kr/news/announcements/",
    },
    "kbo": {
        "target_url": "https://www.koreabaseball.com/Kbo/Board/Notice/List.aspx",
    },
}


def _verify(name: str, source: Dict[str, str]) -> Dict[str, Any]:
    target_url = source["target_url"]
    source_url = source.get("source_url") or target_url
    response = safe_request(
        requests.Session(),
        "GET",
        source_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        },
        timeout=20,
    )
    response.encoding = response.apparent_encoding or "utf-8"
    response.raise_for_status()
    text = response.text
    content_type = response.headers.get("Content-Type", "").casefold()
    is_json = "json" in content_type or text.lstrip().startswith(("{", "["))
    raw_data: Any = response.json() if is_json else text
    source_type = "json" if is_json else "html"
    analysis = analyze_candidate_body(
        text,
        body_shape="json_object" if is_json else "html",
        content_type=content_type,
    )
    result = extract_notices_deterministically(
        raw_data,
        content_type=content_type,
        base_url=target_url if is_json else (response.url or target_url),
    )
    sample = sample_source_structure(raw_data, source_type=source_type)
    candidate = build_rule_based_candidate(raw_data, result)
    execution = None
    gate = None
    if candidate is not None:
        execution = execute_extractor_rule(
            raw_data,
            rule=candidate,
            base_url=target_url if is_json else (response.url or target_url),
        )
        gate = validate_rule_execution(
            execution,
            rule=candidate,
            semantic_record_count=int(analysis.get("semantic_record_count") or 0),
            baseline_notices=result.notices,
        )

    notices = result.notices
    baseline_pairs = {
        (item.get("title"), item.get("detail_url")) for item in notices
    }
    execution_pairs = {
        (item.get("title"), item.get("detail_url"))
        for item in (execution.notices if execution else [])
    }
    return {
        "name": name,
        "target_url": target_url,
        "source_url": response.url or source_url,
        "source_type": source_type,
        "http_status": response.status_code,
        "response_chars": len(text),
        "semantic_record_count": analysis.get("semantic_record_count"),
        "deterministic_status": result.status,
        "deterministic_count": len(notices),
        "record_selector": (result.extractor_config or {}).get("record_css"),
        "records_path": (result.extractor_config or {}).get("records_path"),
        "detail_url_count": sum(bool(item.get("detail_url")) for item in notices),
        "published_at_count": sum(bool(item.get("published_at")) for item in notices),
        "unique_detail_url_count": len(
            {item.get("detail_url") for item in notices if item.get("detail_url")}
        ),
        "sample_metrics": sample.metrics(),
        "rule_candidate": candidate is not None,
        "rule_execution_count": len(execution.notices) if execution else None,
        "hard_gate_passed": gate.passed if gate else None,
        "hard_gate_reasons": gate.reason_codes if gate else [],
        "rule_only_notices": [
            {"title": title, "detail_url": detail_url}
            for title, detail_url in sorted(
                execution_pairs - baseline_pairs, key=lambda item: str(item)
            )[:5]
        ],
        "baseline_only_notices": [
            {"title": title, "detail_url": detail_url}
            for title, detail_url in sorted(
                baseline_pairs - execution_pairs, key=lambda item: str(item)
            )[:5]
        ],
        "first_notices": [
            {
                "title": item.get("title"),
                "detail_url": item.get("detail_url"),
                "published_at": item.get("published_at"),
            }
            for item in notices[:3]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "sources",
        nargs="*",
        choices=sorted(SOURCES),
        default=list(SOURCES),
    )
    args = parser.parse_args()
    results = []
    for name in args.sources:
        try:
            results.append(_verify(name, SOURCES[name]))
        except Exception as exc:
            results.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
