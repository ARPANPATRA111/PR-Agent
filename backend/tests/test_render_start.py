"""Tests for the migration-first Render process entrypoint."""

from unittest.mock import Mock

import pytest

import render_start


def test_render_start_migrates_then_execs_uvicorn(monkeypatch):
    run = Mock()
    execvp = Mock()
    monkeypatch.setenv("PORT", "12345")
    monkeypatch.setattr(render_start.subprocess, "run", run)
    monkeypatch.setattr(render_start.os, "execvp", execvp)

    render_start.main()

    run.assert_called_once_with(
        [render_start.sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
    )
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


@pytest.mark.parametrize("value", ["", "abc", "0", "65536"])
def test_render_start_rejects_invalid_ports(monkeypatch, value):
    monkeypatch.setenv("PORT", value)
    with pytest.raises(RuntimeError, match="PORT"):
        render_start.validated_port()
