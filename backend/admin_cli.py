"""Protected operational CLI. It is never mounted as a public HTTP route."""

from __future__ import annotations

import argparse
import asyncio

from abuse_controls import InviteService, invite_expiry
from memory import get_memory_manager


def create_invite(days: int) -> int:
    memory = get_memory_manager()
    with memory.get_session() as session:
        record, code = InviteService(session).create(
            expires_at_utc=invite_expiry(days),
        )
        print(f"invite_id={record.id}")
        print(f"invite_code={code}")
        print(f"expires_in_days={days}")
    return 0


def run_jobs_once() -> int:
    from inline_staging_worker import build_inline_staging_loop

    processed = asyncio.run(build_inline_staging_loop().run_one_shot())
    print(f"processed_jobs={processed}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="PR-Agent operational CLI")
    commands = parser.add_subparsers(dest="command", required=True)
    invite = commands.add_parser("create-invite")
    invite.add_argument("--expires-days", type=int, default=14)
    commands.add_parser(
        "run-jobs-once",
        help="Run one protected best-effort staging delivery sweep",
    )
    args = parser.parse_args()
    if args.command == "create-invite":
        if not 1 <= args.expires_days <= 365:
            parser.error("--expires-days must be between 1 and 365")
        return create_invite(args.expires_days)
    if args.command == "run-jobs-once":
        return run_jobs_once()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
