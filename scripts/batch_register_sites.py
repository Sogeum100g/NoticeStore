#!/usr/bin/env python3
"""테스트 사이트를 사용자 구독으로 등록하고 크롤링 파이프라인을 실행한다.

기본 실행:
    docker compose exec api python scripts/batch_register_sites.py

목록만 확인:
    python scripts/batch_register_sites.py --dry-run

일부 항목만 실행:
    docker compose exec api python scripts/batch_register_sites.py --match 충남대

주의:
    이 스크립트는 실제 DB에 사이트와 사용자 구독을 저장하고 외부 사이트에
    요청을 보낸다. 기본 테스트 사용자는 user_id=4이며 등록 한도 검사는
    의도적으로 거치지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SITES_PATH = PROJECT_ROOT / "dataController" / "sites.json"
TEST_SITES_PATH = PROJECT_ROOT / "dataController" / "test_sites.json"
DEFAULT_USER_ID = 4


@dataclass
class SiteCase:
    case_id: str
    alias: str
    url: str
    method: str
    source: str
    expected_registration: str | None = None
    minimum_record_count: int | None = None


@dataclass
class SiteResult:
    case_id: str
    alias: str
    submitted_url: str
    canonical_url: str | None
    source: str
    site_id: int | None
    crawl_status: str
    notice_count: int
    expected_registration: str | None
    expectation_met: bool | None
    duration_seconds: float
    error: str | None


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"JSON 최상위 값이 객체가 아닙니다: {path}")
    return data


def _cases_from_sites_json(data: dict[str, Any]) -> Iterable[SiteCase]:
    for method, aliases in data.items():
        if not isinstance(aliases, dict):
            continue
        for alias, url in aliases.items():
            if not isinstance(alias, str) or not isinstance(url, str):
                continue
            yield SiteCase(
                case_id=f"sites:{method.lower()}:{alias}",
                alias=alias.strip(),
                url=url.strip(),
                method=method.upper(),
                source="sites.json",
            )


def _cases_from_test_sites_json(data: dict[str, Any]) -> Iterable[SiteCase]:
    for group_name in ("positive_cases", "negative_cases"):
        cases = data.get(group_name, [])
        if not isinstance(cases, list):
            continue
        for index, item in enumerate(cases, start=1):
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            case_id = str(item.get("id") or f"{group_name}_{index}")
            yield SiteCase(
                case_id=case_id,
                alias=str(item.get("name") or case_id).strip(),
                url=url.strip(),
                method=str(item.get("method") or "GET").upper(),
                source="test_sites.json",
                expected_registration=item.get("expected_registration"),
                minimum_record_count=item.get("minimum_record_count"),
            )


def load_site_cases() -> list[SiteCase]:
    """두 JSON의 항목을 읽고 동일 URL을 하나의 테스트 항목으로 병합한다."""
    merged: dict[str, SiteCase] = {}
    sources_by_url: dict[str, set[str]] = {}

    raw_cases = [
        *_cases_from_sites_json(_read_json(SITES_PATH)),
        *_cases_from_test_sites_json(_read_json(TEST_SITES_PATH)),
    ]
    for case in raw_cases:
        key = case.url.strip()
        sources_by_url.setdefault(key, set()).add(case.source)
        existing = merged.get(key)
        if existing is None:
            merged[key] = case
            continue

        # 같은 URL이 test_sites.json에도 있으면 기대값만 기존 항목에 보강한다.
        if case.expected_registration is not None:
            existing.expected_registration = case.expected_registration
            existing.minimum_record_count = case.minimum_record_count
            existing.case_id = case.case_id

    for url, case in merged.items():
        case.source = "+".join(sorted(sources_by_url[url]))
    return list(merged.values())


def expectation_met(
    expected_registration: str | None,
    crawl_status: str,
    notice_count: int,
    minimum_record_count: int | None,
) -> bool | None:
    if expected_registration is None:
        return None
    if expected_registration == "passed":
        minimum = minimum_record_count or 0
        return crawl_status in {"success", "unchanged"} and notice_count >= minimum
    if expected_registration == "rejected":
        return crawl_status in {"error", "failed", "blocked"} and notice_count == 0
    return None


async def register_and_scrape(case: SiteCase, user_id: int) -> SiteResult:
    """사이트 등록, 사용자 구독 연결, 크롤링을 한 항목에 대해 수행한다."""
    # --dry-run에서는 무거운 크롤러 의존성을 불러오지 않도록 지연 import한다.
    from dataController.scraper.navigation.fetch_policy import expand_url
    from dataController.scraper.pipeline.runner import run_full_scrape
    from dataController.security.url_safety import validate_public_url
    from repositories.notice_repo import (
        add_user_subscription,
        insert_site,
        record_site_submission,
        select_site_id,
    )

    started_at = time.monotonic()
    canonical_url: str | None = None
    site_id: int | None = None

    try:
        expanded_url = await asyncio.to_thread(expand_url, case.url)
        validated = await asyncio.to_thread(validate_public_url, expanded_url)
        canonical_url = validated.url

        site_id = await asyncio.to_thread(select_site_id, canonical_url)
        if site_id is None:
            site_id = await asyncio.to_thread(
                insert_site,
                canonical_url,
                datetime.now(timezone.utc),
                submitted_url=case.url,
                crawl_status="pending",
                validation_status="valid",
            )
        if site_id is None:
            # 동시 실행 중 다른 작업이 먼저 INSERT했을 가능성도 확인한다.
            site_id = await asyncio.to_thread(select_site_id, canonical_url)
        if site_id is None:
            raise RuntimeError("사이트 ID를 생성하거나 조회하지 못했습니다.")

        await asyncio.to_thread(
            record_site_submission,
            site_id,
            submitted_url=case.url,
            validation_status="valid",
        )
        subscribed = await asyncio.to_thread(
            add_user_subscription,
            user_id,
            site_id,
            case.alias,
        )
        if not subscribed:
            raise RuntimeError(f"user_id={user_id} 구독 저장에 실패했습니다.")

        response = await run_full_scrape(canonical_url)
        if not isinstance(response, dict):
            response = {"status": "error", "notices": []}

        response_site_id = response.get("site_id")
        if isinstance(response_site_id, int) and response_site_id != site_id:
            # 예상하지 못한 추가 리다이렉트가 발생해도 최종 사이트가 계정에 보이게 한다.
            final_subscribed = await asyncio.to_thread(
                add_user_subscription,
                user_id,
                response_site_id,
                case.alias,
            )
            if not final_subscribed:
                raise RuntimeError(
                    f"최종 site_id={response_site_id} 구독 저장에 실패했습니다."
                )
            site_id = response_site_id

        crawl_status = str(response.get("status") or "unknown")
        notices = response.get("notices")
        notice_count = len(notices) if isinstance(notices, list) else 0
        error = response.get("error_msg")
        return SiteResult(
            case_id=case.case_id,
            alias=case.alias,
            submitted_url=case.url,
            canonical_url=canonical_url,
            source=case.source,
            site_id=site_id,
            crawl_status=crawl_status,
            notice_count=notice_count,
            expected_registration=case.expected_registration,
            expectation_met=expectation_met(
                case.expected_registration,
                crawl_status,
                notice_count,
                case.minimum_record_count,
            ),
            duration_seconds=round(time.monotonic() - started_at, 2),
            error=str(error) if error else None,
        )
    except Exception as exc:
        return SiteResult(
            case_id=case.case_id,
            alias=case.alias,
            submitted_url=case.url,
            canonical_url=canonical_url,
            source=case.source,
            site_id=site_id,
            crawl_status="exception",
            notice_count=0,
            expected_registration=case.expected_registration,
            expectation_met=False if case.expected_registration else None,
            duration_seconds=round(time.monotonic() - started_at, 2),
            error=f"{type(exc).__name__}: {exc}",
        )


async def run_cases(
    cases: list[SiteCase],
    *,
    user_id: int,
    concurrency: int,
) -> list[SiteResult]:
    semaphore = asyncio.Semaphore(concurrency)
    results: list[SiteResult | None] = [None] * len(cases)

    async def run_one(index: int, case: SiteCase) -> None:
        async with semaphore:
            print(
                f"\n[{index + 1}/{len(cases)}] {case.alias}\n"
                f"  URL: {case.url}",
                flush=True,
            )
            result = await register_and_scrape(case, user_id)
            results[index] = result
            expectation = (
                "-"
                if result.expectation_met is None
                else ("PASS" if result.expectation_met else "FAIL")
            )
            print(
                f"  결과: status={result.crawl_status}, "
                f"site_id={result.site_id}, notices={result.notice_count}, "
                f"expected={expectation}, {result.duration_seconds:.2f}s",
                flush=True,
            )
            if result.error:
                print(f"  오류: {result.error}", flush=True)

    await asyncio.gather(
        *(run_one(index, case) for index, case in enumerate(cases))
    )
    return [result for result in results if result is not None]


def print_case_list(cases: list[SiteCase]) -> None:
    print(f"총 {len(cases)}개 사이트")
    for index, case in enumerate(cases, start=1):
        expected = case.expected_registration or "-"
        print(
            f"{index:>2}. [{case.source}] {case.alias} "
            f"(expected={expected})\n"
            f"    {case.url}"
        )


def print_summary(results: list[SiteResult]) -> None:
    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result.crawl_status] = (
            status_counts.get(result.crawl_status, 0) + 1
        )

    checked = [result for result in results if result.expectation_met is not None]
    passed = sum(result.expectation_met is True for result in checked)
    exceptions = sum(result.crawl_status == "exception" for result in results)

    print("\n=== 실행 요약 ===")
    print(f"전체: {len(results)}개")
    print(
        "상태: "
        + ", ".join(
            f"{status}={count}" for status, count in sorted(status_counts.items())
        )
    )
    print(f"기대값 판정: {passed}/{len(checked)} PASS")
    print(f"예외: {exceptions}개")


def write_report(path: Path, user_id: int, results: list[SiteResult]) -> None:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "result_count": len(results),
        "results": [asdict(result) for result in results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(f"결과 보고서: {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "sites.json과 test_sites.json을 합쳐 테스트 계정에 등록하고 "
            "run_full_scrape()를 실행합니다."
        )
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=DEFAULT_USER_ID,
        help=f"테스트 사용자 ID (기본값: {DEFAULT_USER_ID})",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="동시에 실행할 사이트 수 (기본값: 1)",
    )
    parser.add_argument(
        "--match",
        help="alias, case ID 또는 URL에 이 문자열이 포함된 항목만 실행",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="병합 목록 앞에서부터 지정한 개수만 실행",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB 저장이나 외부 요청 없이 병합된 목록만 출력",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="실행 결과를 저장할 JSON 파일 경로",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.user_id < 1:
        raise SystemExit("--user-id는 1 이상의 정수여야 합니다.")
    if args.concurrency < 1:
        raise SystemExit("--concurrency는 1 이상의 정수여야 합니다.")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit은 1 이상의 정수여야 합니다.")

    # 상대 경로를 사용하는 기존 크롤러 코드와 .env 탐색을 위해 루트에서 실행한다.
    os.chdir(PROJECT_ROOT)
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    cases = load_site_cases()
    if args.match:
        needle = args.match.casefold()
        cases = [
            case
            for case in cases
            if needle
            in " ".join((case.case_id, case.alias, case.url)).casefold()
        ]
    if args.limit is not None:
        cases = cases[: args.limit]

    if not cases:
        print("조건에 맞는 테스트 사이트가 없습니다.")
        return 1
    if args.dry_run:
        print_case_list(cases)
        return 0

    print(
        f"user_id={args.user_id}에 {len(cases)}개 사이트를 등록합니다. "
        f"(concurrency={args.concurrency})",
        flush=True,
    )
    results = asyncio.run(
        run_cases(
            cases,
            user_id=args.user_id,
            concurrency=args.concurrency,
        )
    )
    print_summary(results)
    if args.report:
        write_report(args.report, args.user_id, results)

    # 실행 자체의 예외가 있거나 명시된 기대값이 어긋나면 실패 코드로 종료한다.
    has_failure = any(
        result.crawl_status == "exception" or result.expectation_met is False
        for result in results
    )
    return 1 if has_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
