"""Print recent extraction-agent rollout metrics as JSON."""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from repositories.notice_repo import get_extraction_agent_rollout_summary


def _json_default(value):
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    result = get_extraction_agent_rollout_summary(
        hours=args.hours,
        recent_limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
