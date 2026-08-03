"""Safety and happy-path coverage for staging deployment utilities."""

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "url",
    [
        "https://pr-agent-staging-api.onrender.com",
        "https://pr-agent-production-api.onrender.com",
        "http://pr-agent-r24-staging-api.onrender.com",
        "https://unrelated-staging-api.onrender.com",
    ],
)
def test_activation_coordinator_refuses_unapproved_urls(url):
    module = load_script("activate_staging_bot.py")
    with pytest.raises(ValueError):
        module.validate_staging_api_url(url)


def test_activation_dry_run_never_prints_secrets(monkeypatch, capsys):
    module = load_script("activate_staging_bot.py")
    token = "123456:do-not-print-this-token"
    secret = "do-not-print-this-webhook-secret"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", secret)
    monkeypatch.setattr(sys, "argv", ["activate_staging_bot.py", "--dry-run"])

    assert module.main() == 0
    output = capsys.readouterr()
    assert token not in output.out + output.err
    assert secret not in output.out + output.err
    assert "mutation_planned=false" in output.out


def test_deployment_diagnostic_checks_pre_bot_profile(monkeypatch):
    module = load_script("verify_staging_deployment.py")
    api = "https://pr-agent-r24-staging-api.onrender.com"
    frontend = "https://pr-agent-r24-staging-web.onrender.com"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "healthy"})
        if request.url.path == "/ready":
            return httpx.Response(
                200,
                json={
                    "migration_revision": module.EXPECTED_REVISION,
                    "environment": "staging",
                    "debug": False,
                    "components": {
                        "telegram": "disabled",
                        "telegram_delivery": "awaiting_telegram",
                        "ai": "disabled",
                        "nutrition_provider": "disabled",
                        "message_cleanup": "disabled",
                    },
                },
            )
        if request.url.path == "/webhook":
            return httpx.Response(503)
        if request.method == "OPTIONS":
            return httpx.Response(
                200,
                headers={"access-control-allow-origin": frontend},
            )
        return httpx.Response(200, text="PR-Agent staging")

    original_client = module.httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )

    results = module.verify(
        api,
        frontend,
        expected_revision=module.EXPECTED_REVISION,
    )
    assert results == [
        "health=pass",
        "readiness=pass",
        "telegram_disabled=pass",
        "frontend=pass",
        "cors=pass",
        "delivery_metrics=skip(no token)",
    ]
