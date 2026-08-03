import importlib.util
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def load_yaml(name: str) -> dict:
    return yaml.safe_load((REPOSITORY_ROOT / name).read_text(encoding="utf-8"))


def test_free_blueprint_contains_only_free_api_and_static_site():
    blueprint = load_yaml("render.free.yaml")
    assert set(blueprint) == {"services"}
    services = blueprint["services"]
    assert [service["name"] for service in services] == [
        "pr-agent-r24-staging-api",
        "pr-agent-r24-staging-web",
    ]
    assert [service["type"] for service in services] == ["web", "web"]
    assert services[0]["plan"] == "free"
    assert services[1]["runtime"] == "static"
    assert "plan" not in services[1]
    assert "alembic upgrade head" in services[0]["dockerCommand"]
    assert "$PORT" in services[0]["dockerCommand"]
    assert (REPOSITORY_ROOT / "backend" / "Dockerfile").is_file()
    assert (REPOSITORY_ROOT / "backend" / "migrations").is_dir()
    assert (REPOSITORY_ROOT / "frontend" / "next.config.js").is_file()

    environment = {item["key"]: item.get("value") for item in services[0]["envVars"]}
    assert environment["PUBLIC_V2_ENABLED"] == "true"
    assert environment["TELEGRAM_INTEGRATION_ENABLED"] == "false"
    assert environment["INLINE_STAGING_WORKER_ENABLED"] == "true"
    assert environment["REMINDER_WORKER_ENABLED"] == "false"
    assert environment["AI_AGENT_ENABLED"] == "false"
    assert environment["AI_PROVIDER"] == "disabled"
    assert environment["NUTRITION_PROVIDER"] == "disabled"
    assert environment["MESSAGE_CLEANUP_ENABLED"] == "false"
    assert "TELEGRAM_BOT_TOKEN" not in environment


def test_free_blueprint_structurally_rejects_billable_resources():
    blueprint = load_yaml("render.free.yaml")
    forbidden_keys = {
        "projects",
        "environments",
        "envVarGroups",
        "databases",
        "keyvalue",
        "redis",
        "disk",
        "disks",
        "maintenanceMode",
        "previews",
        "previewPlan",
        "scaling",
        "autoscaling",
        "highAvailability",
        "readReplicas",
        "numInstances",
    }
    forbidden_types = {"worker", "cron", "workflow", "pserv", "private_service"}
    paid_plans = {
        "starter",
        "standard",
        "pro",
        "pro_plus",
        "pro_max",
        "pro_ultra",
    }

    def walk(value):
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value.keys())
            if "type" in value:
                assert str(value["type"]).lower() not in forbidden_types
            if "plan" in value:
                assert str(value["plan"]).lower() not in paid_plans
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(blueprint)
    services = blueprint["services"]
    assert len(services) == 2
    assert sum(service.get("plan") == "free" for service in services) == 1
    assert sum(service.get("runtime") == "static" for service in services) == 1


def test_production_blueprint_keeps_dedicated_worker():
    services = load_yaml("render.yaml")["projects"][0]["environments"][0]["services"]
    assert any(service["type"] == "worker" for service in services)


def test_registered_commands_include_manual_food_and_exclude_legacy_reports():
    script_path = REPOSITORY_ROOT / "scripts" / "register_bot_commands.py"
    spec = importlib.util.spec_from_file_location("register_bot_commands", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    commands = [command for command, _description in module.PUBLIC_COMMANDS]
    assert "savefoodnote" in commands
    assert len(commands) == len(set(commands))
    assert not {"linkedin", "report", "post"}.intersection(commands)
