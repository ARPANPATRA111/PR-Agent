"""Render entrypoint: migrate the database, then replace this process with Uvicorn."""

from __future__ import annotations

import os
import sys

from database_migrations import upgrade_database_schema


def validated_port() -> str:
    value = os.environ.get("PORT", "8000")
    if not value.isdigit() or not 1 <= int(value) <= 65535:
        raise RuntimeError("PORT must be an integer between 1 and 65535")
    return value


def main(command: list[str] | None = None) -> None:
    """Migrate, then execute either the container command or the web server."""
    upgrade_database_schema()
    target = list(command or [])
    if not target:
        port = validated_port()
        target = [
            "uvicorn",
            "main:app",
            "--host",
            "0.0.0.0",
            "--port",
            port,
            "--workers",
            "1",
        ]
    os.execvp(target[0], target)


if __name__ == "__main__":
    main(sys.argv[1:])
