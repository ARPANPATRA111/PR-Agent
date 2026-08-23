"""Tests for the shared, migration-first process guard."""

from unittest.mock import Mock

import database_migrations


def test_upgrade_database_schema_uses_a_fixed_shell_free_command(monkeypatch):
    run = Mock()
    monkeypatch.setattr(database_migrations.subprocess, "run", run)

    database_migrations.upgrade_database_schema(timeout_seconds=123)

    run.assert_called_once_with(
        [
            database_migrations.sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
        ],
        cwd=database_migrations.BACKEND_DIRECTORY,
        check=True,
        timeout=123,
    )
