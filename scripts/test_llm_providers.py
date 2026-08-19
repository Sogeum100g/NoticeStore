"""OpenAI와 Gemini 후보 선택 경로를 실제 API로 점검한다.

Usage:
    python scripts/test_llm_providers.py
    python scripts/test_llm_providers.py --provider gemini
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Callable, Dict, List

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from dataController.selector.candidate_selector import (  # noqa: E402
    _call_gemini_select_candidate,
    _call_openai_select_candidate,
)


SMOKE_CANDIDATES = [
    {
        "api_index": 0,
        "method_type": "GET",
        "type": "xhr",
        "source_kind": "network",
        "api_url": "https://example.com/api/notices",
        "content_type": "application/json",
        "score": 25,
        "data_key_hits": ["title", "date", "items"],
        "body_shape": "object_with_list",
        "has_callback_param": False,
        "payload_keys": [],
        "feature_summary": {
            "has_title_key": True,
            "has_date_key": True,
            "has_list_key": True,
            "has_repeated_records": True,
            "semantic_record_count": 3,
            "looks_like_non_content": False,
            "is_json_like": True,
        },
        "sample": '{"items":[{"title":"공지 1","date":"2026-08-19"}]}',
    }
]


def _redact_secrets(message: str) -> str:
    for name in (
        "OPEN_AI_API_KEY_SELECT_API",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY_SELECT_API",
        "GEMINI_API_KEY",
    ):
        secret = os.getenv(name)
        if secret:
            message = message.replace(secret, "<redacted>")
    return message


def _run_provider(
    provider: str,
    call: Callable[[List[Dict]], Dict],
) -> bool:
    try:
        result = call(SMOKE_CANDIDATES)
    except Exception as exc:
        print(f"FAIL {provider}: {_redact_secrets(str(exc))}")
        return False

    usage = result.get("_usage") or {}
    print(
        f"PASS {provider}: model={usage.get('model')} "
        f"input_tokens={usage.get('input_tokens', 0)} "
        f"output_tokens={usage.get('output_tokens', 0)} "
        f"index={result.get('index')}"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="실제 LLM 공급자 연결을 점검합니다.")
    parser.add_argument(
        "--provider",
        choices=("all", "openai", "gemini"),
        default="all",
    )
    args = parser.parse_args()

    providers = {
        "openai": _call_openai_select_candidate,
        "gemini": _call_gemini_select_candidate,
    }
    selected = (
        providers.items()
        if args.provider == "all"
        else [(args.provider, providers[args.provider])]
    )
    passed = [_run_provider(name, call) for name, call in selected]
    return 0 if all(passed) else 1


if __name__ == "__main__":
    raise SystemExit(main())
