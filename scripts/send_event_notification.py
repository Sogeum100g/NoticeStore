"""Send an operator-triggered FCM notification for a predefined event.

The command is a dry run unless ``--confirm`` is supplied.  Examples:

    python scripts/send_event_notification.py \
        --event app_update --version-code 12 --user-id 7

    python scripts/send_event_notification.py \
        --event app_update --version-code 12 --all --confirm
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from firebase_admin import messaging
from psycopg.rows import dict_row

from repositories.db_manager import get_db_connection
from services.notify_service import initialize_firebase


FCM_BATCH_SIZE = 500
ANDROID_NOTIFICATION_CHANNEL_ID = "notice_store_updates"


@dataclass(frozen=True)
class Recipient:
    """One unique FCM token and the DB rows that contain it."""

    token: str
    token_ids: tuple[int, ...]
    user_ids: tuple[int, ...]


@dataclass(frozen=True)
class EventMessage:
    title: str
    body: str
    data: dict[str, str]


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("0보다 큰 정수를 입력해야 합니다.")
    return parsed


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "DB에 저장된 Android FCM 토큰으로 이벤트 안내를 발송합니다. "
            "--confirm을 지정하지 않으면 대상만 확인하는 dry-run입니다."
        )
    )
    parser.add_argument(
        "--event",
        choices=("app_update",),
        required=True,
        help="발송할 이벤트 종류",
    )
    parser.add_argument(
        "--version-code",
        type=_positive_int,
        help="app_update 이벤트의 Android versionCode",
    )
    parser.add_argument(
        "--title",
        help="기본 알림 제목을 덮어쓸 때 사용",
    )
    parser.add_argument(
        "--body",
        help="기본 알림 본문을 덮어쓸 때 사용",
    )

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--user-id", type=_positive_int, help="테스트 사용자 ID")
    target.add_argument("--email", help="테스트 사용자 이메일")
    target.add_argument(
        "--all",
        action="store_true",
        help="FCM 토큰이 등록된 모든 Android 기기",
    )

    execution = parser.add_mutually_exclusive_group()
    execution.add_argument(
        "--confirm",
        action="store_true",
        help="실제로 알림을 발송합니다.",
    )
    execution.add_argument(
        "--dry-run",
        action="store_true",
        help="발송하지 않고 대상과 메시지만 확인합니다(기본값).",
    )

    args = parser.parse_args(argv)
    if args.event == "app_update" and args.version_code is None:
        parser.error("app_update 이벤트에는 --version-code가 필요합니다.")
    if args.email is not None:
        args.email = args.email.strip()
        if not args.email:
            parser.error("--email은 비어 있을 수 없습니다.")
    return args


def _build_event_message(args: argparse.Namespace) -> EventMessage:
    if args.event != "app_update":
        raise ValueError(f"지원하지 않는 이벤트입니다: {args.event}")

    return EventMessage(
        title=args.title or "공지저장소 업데이트 안내 😁",
        body=args.body
        or (
            "새로운 버전이 출시되었습니다. "
            "Google Play 스토어에서 최신 버전으로 업데이트해 주세요."
        ),
        data={
            "type": "app_update",
            "version_code": str(args.version_code),
        },
    )


def _load_recipients(args: argparse.Namespace) -> list[Recipient]:
    clauses = [
        "LOWER(COALESCE(t.device_type, '')) = 'android'",
        "NULLIF(BTRIM(t.fcm_token), '') IS NOT NULL",
    ]
    params: list[object] = []

    if args.user_id is not None:
        clauses.append("u.user_id = %s")
        params.append(args.user_id)
    elif args.email is not None:
        clauses.append("LOWER(u.email) = LOWER(%s)")
        params.append(args.email)

    connection = get_db_connection()
    if connection is None:
        raise RuntimeError("DB에 연결할 수 없습니다.")

    try:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT t.token_id, t.user_id, t.fcm_token
                FROM user_fcm_tokens t
                JOIN users u ON u.user_id = t.user_id
                WHERE {' AND '.join(clauses)}
                ORDER BY t.token_id
                """,
                params,
            )
            rows = cursor.fetchall()
    finally:
        connection.close()

    # 한 FCM 토큰이 여러 사용자/기기 행에 남아 있어도 실제 발송은 한 번만 합니다.
    grouped: dict[str, dict[str, set[int]]] = {}
    for row in rows:
        token = str(row["fcm_token"]).strip()
        entry = grouped.setdefault(token, {"token_ids": set(), "user_ids": set()})
        entry["token_ids"].add(int(row["token_id"]))
        entry["user_ids"].add(int(row["user_id"]))

    return [
        Recipient(
            token=token,
            token_ids=tuple(sorted(values["token_ids"])),
            user_ids=tuple(sorted(values["user_ids"])),
        )
        for token, values in grouped.items()
    ]


def _chunks(items: Sequence[Recipient], size: int) -> Iterable[Sequence[Recipient]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _delete_invalid_tokens(token_ids: Iterable[int]) -> int:
    ids = sorted(set(token_ids))
    if not ids:
        return 0

    connection = get_db_connection()
    if connection is None:
        print("⚠️ 만료 토큰을 삭제하기 위한 DB 연결에 실패했습니다.")
        return 0

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM user_fcm_tokens WHERE token_id = ANY(%s)",
                (ids,),
            )
            deleted = cursor.rowcount
        connection.commit()
        return deleted
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _send(
    recipients: Sequence[Recipient],
    event_message: EventMessage,
) -> dict[str, int]:
    initialize_firebase()

    sent = 0
    failed = 0
    invalid_token_ids: list[int] = []

    for batch_number, batch in enumerate(
        _chunks(recipients, FCM_BATCH_SIZE),
        start=1,
    ):
        multicast_message = messaging.MulticastMessage(
            notification=messaging.Notification(
                title=event_message.title,
                body=event_message.body,
            ),
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    channel_id=ANDROID_NOTIFICATION_CHANNEL_ID,
                    sound="default",
                ),
            ),
            data=event_message.data,
            tokens=[recipient.token for recipient in batch],
        )

        try:
            response = messaging.send_each_for_multicast(multicast_message)
        except Exception as exc:
            failed += len(batch)
            print(f"❌ 배치 {batch_number} 발송 자체가 실패했습니다: {exc}")
            continue

        sent += response.success_count
        failed += response.failure_count
        print(
            f"배치 {batch_number}: 성공 {response.success_count}, "
            f"실패 {response.failure_count}"
        )

        for recipient, result in zip(batch, response.responses):
            if result.success:
                continue
            if isinstance(result.exception, messaging.UnregisteredError):
                invalid_token_ids.extend(recipient.token_ids)

    deleted = _delete_invalid_tokens(invalid_token_ids)
    return {
        "target_count": len(recipients),
        "sent": sent,
        "failed": failed,
        "deleted_invalid_tokens": deleted,
    }


def _target_description(args: argparse.Namespace) -> str:
    if args.user_id is not None:
        return f"user_id={args.user_id}"
    if args.email is not None:
        return f"email={args.email}"
    return "모든 Android 등록 기기"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    event_message = _build_event_message(args)

    try:
        recipients = _load_recipients(args)
    except Exception as exc:
        print(f"❌ 발송 대상 조회 실패: {exc}", file=sys.stderr)
        return 1

    user_count = len(
        {
            user_id
            for recipient in recipients
            for user_id in recipient.user_ids
        }
    )
    preview = {
        "mode": "send" if args.confirm else "dry-run",
        "event": args.event,
        "target": _target_description(args),
        "user_count": user_count,
        "unique_token_count": len(recipients),
        "title": event_message.title,
        "body": event_message.body,
        "data": event_message.data,
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))

    if not recipients:
        print("발송할 Android FCM 토큰이 없습니다.")
        return 1

    if not args.confirm:
        print("DRY-RUN: 실제 발송은 하지 않았습니다. 발송하려면 --confirm을 추가하세요.")
        return 0

    try:
        result = _send(recipients, event_message)
    except Exception as exc:
        print(f"❌ 알림 발송 실패: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
