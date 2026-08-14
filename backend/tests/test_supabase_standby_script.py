from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prepare_supabase_standby.py"
SPEC = spec_from_file_location("prepare_supabase_standby", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
standby = module_from_spec(SPEC)
SPEC.loader.exec_module(standby)


def test_accepts_direct_supabase_postgres(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    value = "postgresql://postgres:secret@db.project.supabase.co:5432/postgres"
    assert standby.validate_target(value) == value


def test_accepts_supabase_session_pooler(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    value = (
        "postgresql://postgres.project:secret@"
        "aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"
    )
    assert standby.validate_target(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "sqlite:///standby.db",
        "postgresql://postgres:secret@example.com:5432/postgres",
        (
            "postgresql://postgres.project:secret@"
            "aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres"
        ),
    ],
)
def test_rejects_unsafe_targets(monkeypatch, value):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        standby.validate_target(value)


def test_refuses_active_database(monkeypatch):
    value = "postgresql://postgres:secret@db.project.supabase.co:5432/postgres"
    monkeypatch.setenv("DATABASE_URL", value)
    with pytest.raises(RuntimeError, match="active DATABASE_URL"):
        standby.validate_target(value)


def test_sanitized_target_never_contains_credentials():
    value = (
        "postgresql://postgres.project:super-secret@"
        "aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"
    )
    sanitized = standby.sanitized_target(value)
    assert sanitized == "aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"
    assert "secret" not in sanitized
