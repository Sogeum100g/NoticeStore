import datetime
from typing import Any, Dict, Optional, Tuple


def classify_processing_result(
    result: Optional[Dict[str, Any]],
) -> Tuple[str, Optional[str]]:
    """Translate an extractor result into the persisted processing state."""
    if not result:
        return "failed", "추출기가 결과를 반환하지 않았습니다."

    if result.get("status") == "error":
        return "failed", result.get("error_msg") or "공지 구조화에 실패했습니다."

    notices = result.get("notices")
    if not isinstance(notices, list):
        return "failed", "추출 결과의 notices가 배열이 아닙니다."
    if not notices:
        return "valid_empty", None
    return "success", None


def decide_observation(
    observed_hash: str,
    state: Dict[str, Any],
    *,
    now: Optional[datetime.datetime] = None,
    max_retries: int = 3,
) -> str:
    """Return process, unchanged, backoff, or retry_exhausted."""
    if observed_hash and observed_hash == (
        state.get("last_processed_hash") or state.get("last_hash")
    ):
        return "unchanged"

    same_failed_source = (
        state.get("processing_status") == "failed"
        and observed_hash
        and observed_hash == state.get("last_observed_hash")
    )
    if not same_failed_source:
        return "process"

    if int(state.get("retry_count") or 0) >= max_retries:
        return "retry_exhausted"

    next_retry_at = state.get("next_retry_at")
    if not next_retry_at:
        return "process"
    if isinstance(next_retry_at, str):
        try:
            next_retry_at = datetime.datetime.fromisoformat(
                next_retry_at.replace("Z", "+00:00")
            )
        except ValueError:
            return "process"
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if next_retry_at.tzinfo is None:
        next_retry_at = next_retry_at.replace(tzinfo=datetime.timezone.utc)
    if now < next_retry_at:
        return "backoff"
    return "process"
