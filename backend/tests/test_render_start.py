"""Tests for the migration-first Render process entrypoint."""

from unittest.mock import Mock

import pytest

import render_start


def test_render_start_migrates_then_execs_uvicorn(monkeypatch):
    migrate = Mock()
    execvp = Mock()
    monkeypatch.setenv("PORT", "12345")
    monkeypatch.setattr(render_start, "upgrade_database_schema", migrate)
    monkeypatch.setattr(render_start.os, "execvp", execvp)

    render_start.main()

    migrate.assert_called_once_with()
    execvp.assert_called_once_with(
        "uvicorn",
        [
            "uvicorn",
            "main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "12345",
            "--workers",
            "1",
        ],
    )


def test_render_start_migrates_then_execs_supplied_container_command(monkeypatch):
    migrate = Mock()
    execvp = Mock()
    monkeypatch.setattr(render_start, "upgrade_database_schema", migrate)
    monkeypatch.setattr(render_start.os, "execvp", execvp)

    render_start.main(["python", "worker.py"])

    migrate.assert_called_once_with()
    execvp.assert_called_once_with("python", ["python", "worker.py"])


@pytest.mark.parametrize("value", ["", "abc", "0", "65536"])
def test_render_start_rejects_invalid_ports(monkeypatch, value):
    monkeypatch.setenv("PORT", value)
    with pytest.raises(RuntimeError, match="PORT"):
        render_start.validated_port()
