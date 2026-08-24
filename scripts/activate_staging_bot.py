#!/usr/bin/env python3
"""Safely inspect or activate Telegram for the isolated free staging API."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from register_bot_commands import register_commands, telegram_call  # noqa: E402
from setup_webhook import (  # noqa: E402
    ALLOWED_UPDATES,
    get_webhook_info,
    set_webhook,
)

EXPECTED_HOST = "pr-agent-r24-staging-api.onrender.com"
RETIRED_HOST = "pr-agent-staging-api.onrender.com"
WEBHOOK_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")


def validate_staging_api_url(value: str) -> str:
    parsed = urlparse(value.rstrip("/"))
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.path not in {"", "/"}:
        raise ValueError("Staging API URL must be an HTTPS origin without a path")
    if host == RETIRED_HOST or "prod" in host or "production" in host:
        raise ValueError("Refusing a retired or production-looking API URL")
    if host != EXPECTED_HOST:
        raise ValueError(f"Refusing unapproved host; expected {EXPECTED_HOST}")
    return f"https://{host}"


def required_secret(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is required through protected configuration")
    return value


def validate_webhook_secret(value: str) -> str:
    if not WEBHOOK_SECRET_PATTERN.fullmatch(value):
        raise RuntimeError(
            "TELEGRAM_WEBHOOK_SECRET must contain 16-256 characters using only "
            "letters, digits, underscores, and hyphens"
        )
    return value


async def status(token: str) -> None:
    bot = (await telegram_call(token, "getMe"))["result"]
    commands = (await telegram_call(token, "getMyCommands"))["result"]
    webhook = await get_webhook_info(token)
    if not webhook.get("ok"):
        raise RuntimeError(webhook.get("description", "getWebhookInfo failed"))
    info = webhook["result"]
    print(f"bot_id={bot.get('id')}")
    print(f"bot_username=@{bot.get('username', '')}")
    print(f"registered_commands={len(commands)}")
    print(f"webhook_url={info.get('url') or '(not set)'}")
    print("allowed_updates=" + ",".join(sorted(info.get("allowed_updates") or [])))
    print(f"pending_updates={info.get('pending_update_count', 0)}")


async def activate(api_url: str, token: str, secret: str) -> None:
    bot = (await telegram_call(token, "getMe"))["result"]
    print(f"validated_bot=@{bot.get('username', '')}")
    await register_commands(token, verify_only=False)
    result = await set_webhook(api_url, token, secret)
    if not result.get("ok"):
        raise RuntimeError(result.get("description", "setWebhook failed"))
    info = await get_webhook_info(token)
    if not info.get("ok"):
        raise RuntimeError(info.get("description", "getWebhookInfo failed"))
    actual_url = info["result"].get("url")
    expected_url = f"{api_url}/webhook"
    if actual_url != expected_url:
        raise RuntimeError("Telegram reported an unexpected webhook URL")
    actual_updates = set(info["result"].get("allowed_updates") or [])
    missing_updates = set(ALLOWED_UPDATES) - actual_updates
    if missing_updates:
        missing = ", ".join(sorted(missing_updates))
        raise RuntimeError(
            "Telegram webhook is missing required update types: " + missing
        )
    await register_commands(token, verify_only=True)
    print(f"webhook_url={actual_url}")
    print("allowed_updates=" + ",".join(sorted(actual_updates)))
    print("activation_verified=true")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=f"https://{EXPECTED_HOST}")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--status", action="store_true")
    args = parser.parse_args()

    try:
        api_url = validate_staging_api_url(args.api_url)
        if args.dry_run:
            token_present = bool(os.environ.get("TELEGRAM_BOT_TOKEN"))
            secret_present = bool(os.environ.get("TELEGRAM_WEBHOOK_SECRET"))
            print(f"api_url={api_url}")
            print(f"telegram_token_present={str(token_present).lower()}")
            print(f"webhook_secret_present={str(secret_present).lower()}")
            print("mutation_planned=false")
            return 0 if token_present and secret_present else 2

        token = required_secret("TELEGRAM_BOT_TOKEN")
        if ":" not in token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN has an invalid format")
        if args.status:
            asyncio.run(status(token))
        else:
            secret = validate_webhook_secret(required_secret("TELEGRAM_WEBHOOK_SECRET"))
            asyncio.run(activate(api_url, token, secret))
        return 0
    except (RuntimeError, ValueError) as exc:
        print(f"error={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
