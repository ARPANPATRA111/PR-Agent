"""Render entrypoint: migrate the database, then replace this process with Uvicorn."""

from __future__ import annotations

import os
import subprocess
import sys


def validated_port() -> str:
    value = os.environ.get("PORT", "8000")
    if not value.isdigit() or not 1 <= int(value) <= 65535:
        raise RuntimeError("PORT must be an integer between 1 and 65535")
    return value


def main() -> None:
    port = validated_port()
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
    )
    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "main:app",
            "--host",
            "0.0.0.0",
            "--port",
            port,
            "--workers",
            "1",
        ],
    )


if __name__ == "__main__":
    main()
