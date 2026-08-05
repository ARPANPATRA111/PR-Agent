#!/usr/bin/env python3
"""Run privacy-safe checks against the free staging API and static site."""

from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlparse

import httpx

EXPECTED_REVISION = "h3d5f7a9c1e2"
RETIRED_HOSTS = {
    "pr-agent-staging-api.onrender.com",
    "pr-agent-staging-web.onrender.com",
}


def validated_origin(value: str, label: str) -> str:
    parsed = urlparse(value.rstrip("/"))
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.path not in {"", "/"}:
        raise ValueError(f"{label} must be an HTTPS origin without a path")
    if host in RETIRED_HOSTS or "prod" in host or "production" in host:
        raise ValueError(f"Refusing retired or production-looking {label}")
    if not host.endswith(".onrender.com") or "staging" not in host:
        raise ValueError(f"Refusing non-staging {label}")
    return f"https://{host}"


def require(response: httpx.Response, expected: int, label: str) -> None:
    if response.status_code != expected:
        raise RuntimeError(f"{label} returned HTTP {response.status_code}")


def verify(
    api_url: str,
    frontend_url: str,
    *,
    expected_revision: str,
    monitoring_token: str = "",
) -> list[str]:
    results: list[str] = []
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        health = client.get(f"{api_url}/health")
        require(health, 200, "health")
        if health.json().get("status") != "healthy":
            raise RuntimeError("health payload is not healthy")
        results.append("health=pass")

        ready = client.get(f"{api_url}/ready")
        require(ready, 200, "readiness")
        payload = ready.json()
        if payload.get("migration_revision") != expected_revision:
            raise RuntimeError("database migration revision does not match")
        if payload.get("environment") != "staging" or payload.get("debug") is not False:
            raise RuntimeError("staging environment or debug state is unsafe")
        components = payload.get("components", {})
        expected = {
            "telegram": "disabled",
            "telegram_delivery": "awaiting_telegram",
            "ai": "disabled",
            "nutrition_provider": "disabled",
            "message_cleanup": "disabled",
        }
        if any(components.get(key) != value for key, value in expected.items()):
            raise RuntimeError(
                "pre-bot component state does not match the free profile"
            )
        results.append("readiness=pass")

        webhook = client.post(f"{api_url}/webhook", json={"update_id": 1})
        require(webhook, 503, "disabled webhook")
        results.append("telegram_disabled=pass")

        frontend = client.get(frontend_url)
        require(frontend, 200, "frontend")
        body = frontend.text.lower()
        if any(host in body for host in RETIRED_HOSTS):
            raise RuntimeError("frontend contains a retired deployment URL")
        expected_headers = {
            "x-content-type-options": "nosniff",
            "referrer-policy": "no-referrer",
            "permissions-policy": "camera=(), geolocation=(), microphone=()",
        }
        for name, value in expected_headers.items():
            if frontend.headers.get(name) != value:
                raise RuntimeError(f"frontend security header is missing: {name}")
        results.append("frontend=pass")

        route_refresh = client.get(f"{frontend_url}/settings")
        require(route_refresh, 200, "frontend route refresh")
        results.append("route_refresh=pass")

        preflight = client.options(
            f"{api_url}/api/health",
            headers={
                "Origin": frontend_url,
                "Access-Control-Request-Method": "GET",
            },
        )
        require(preflight, 200, "CORS preflight")
        if preflight.headers.get("access-control-allow-origin") != frontend_url:
            raise RuntimeError("CORS origin does not match the staging frontend")
        results.append("cors=pass")

        if monitoring_token:
            metrics = client.get(
                f"{api_url}/internal/metrics",
                headers={"Authorization": f"Bearer {monitoring_token}"},
            )
            require(metrics, 200, "internal metrics")
            deliveries = metrics.json().get("deliveries", {})
            for key in (
                "reminder_failed",
                "digest_failed",
                "telegram_cleanup_failed",
                "due_job_lag_seconds",
            ):
                if not isinstance(deliveries.get(key), int):
                    raise RuntimeError("internal delivery metrics are incomplete")
            results.append("delivery_metrics=pass")
        else:
            results.append("delivery_metrics=skip(no token)")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--frontend-url", required=True)
    parser.add_argument("--expected-revision", default=EXPECTED_REVISION)
    args = parser.parse_args()
    try:
        api_url = validated_origin(args.api_url, "API URL")
        frontend_url = validated_origin(args.frontend_url, "frontend URL")
        results = verify(
            api_url,
            frontend_url,
            expected_revision=args.expected_revision,
            monitoring_token=os.environ.get("INTERNAL_MONITORING_TOKEN", ""),
        )
        print("\n".join(results))
        print("deployment_verification=pass")
        return 0
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        print(f"deployment_verification=fail ({exc})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
