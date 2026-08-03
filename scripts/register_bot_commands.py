#!/usr/bin/env python3
"""Idempotently register the public Telegram command menu."""

from __future__ import annotations

import argparse
import asyncio
import os

import httpx

PUBLIC_COMMANDS = [
    ("start", "Open PR-Agent"),
    ("help", "Show available commands"),
    ("log", "Add a work log"),
    ("logs", "List recent work logs"),
    ("editlog", "Edit a work log"),
    ("deletelog", "Delete a work log"),
    ("note", "Add a note"),
    ("notes", "List notes"),
    ("editnote", "Edit a note"),
    ("pin", "Pin or unpin a note"),
    ("deletenote", "Delete a note"),
    ("expense", "Record an expense"),
    ("income", "Record income"),
    ("ledger", "List money entries"),
    ("editledger", "Edit a money entry"),
    ("deleteledger", "Delete a money entry"),
    ("goal", "Create a goal"),
    ("goals", "List goals"),
    ("editgoal", "Edit a goal"),
    ("goalprogress", "Update goal progress"),
    ("completegoal", "Complete a goal"),
    ("pausegoal", "Pause a goal"),
    ("deletegoal", "Delete a goal"),
    ("remind", "Create a reminder"),
    ("reminders", "List reminders"),
    ("editreminder", "Edit a reminder"),
    ("pausereminder", "Pause a reminder"),
    ("resumereminder", "Resume a reminder"),
    ("deletereminder", "Delete a reminder"),
    ("food", "Add a food log"),
    ("nutrition", "Show nutrition totals"),
    ("confirmfood", "Confirm a food estimate"),
    ("editfood", "Edit a food item"),
    ("deletefood", "Delete a food log"),
    ("nutritiontargets", "Set nutrition targets"),
    ("today", "Show today's summary"),
    ("week", "Show this week's summary"),
    ("spending", "Show spending totals"),
    ("settings", "Open settings"),
    ("export", "Export your data"),
    ("deleteaccount", "Delete your account"),
    ("answeragent", "Answer an assistant question"),
    ("confirmagent", "Confirm an assistant action"),
    ("cancelagent", "Cancel an assistant action"),
]


async def telegram_call(token: str, method: str, payload: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{token}/{method}",
            json=payload or {},
        )
        response.raise_for_status()
        result = response.json()
    if not result.get("ok"):
        raise RuntimeError(result.get("description", f"Telegram {method} failed"))
    return result


async def run(*, verify_only: bool) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token or ":" not in token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    expected = [
        {"command": command, "description": description}
        for command, description in PUBLIC_COMMANDS
    ]
    if not verify_only:
        await telegram_call(token, "setMyCommands", {"commands": expected})
    actual = (await telegram_call(token, "getMyCommands"))["result"]
    if actual != expected:
        raise RuntimeError("Telegram command menu does not match the public registry")
    print(f"registered_commands={len(actual)}")
    print("legacy_commands_present=false")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(verify_only=args.verify_only))


if __name__ == "__main__":
    raise SystemExit(main())
