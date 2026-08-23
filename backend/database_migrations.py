"""Run the reviewed Alembic migration chain before serving application traffic."""

from __future__ import annotations

from pathlib import Path
# This module only executes the fixed Alembic argv declared below.
import subprocess  # nosec B404
import sys


BACKEND_DIRECTORY = Path(__file__).resolve().parent


def upgrade_database_schema(*, timeout_seconds: int = 300) -> None:
    """Upgrade the configured database with a fixed, shell-free command."""
    # The argv and working directory are constants; no shell is involved.
    subprocess.run(  # nosec B603
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIRECTORY,
        check=True,
        timeout=timeout_seconds,
    )
