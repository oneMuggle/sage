"""通用外部服务状态路由：形状正确、探活失败可读、密钥绝不回显。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import external_service_routes
from backend.services.external_services.spec import ExternalServiceSpec


def _client(spec: ExternalServiceSpec) -> TestClient:
    app = FastAPI()
    app.include_router(
        external_service_routes.build_external_service_router(spec), prefix="/api/v1"
    )
    return TestClient(app)


def _spec(name: str, probe=None) -> ExternalServiceSpec:
    return ExternalServiceSpec(
        name=name,
        preference_key=f"{name}_service",
        api_prefix=name,
        probe=probe,
    )


def test_status_never_leaks_key_and_reports_probe_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        external_service_routes,
        "load_service_settings",
        lambda spec: {"enabled": True, "baseUrl": "http://demo", "apiKey": "sk-synthetic"},
    )

    async def fake_probe(values):
        assert values["apiKey"] == "sk-synthetic"
        return {
            "reachable": True,
            "serverAuthMode": "bearer",
            "serverVersion": "1.0",
            "reason": "",
        }

    response = _client(_spec("demo", fake_probe)).get("/api/v1/demo/status")
    body = response.json()

    assert "sk-synthetic" not in response.text
    assert "apiKey" not in body
    for key in ("configured", "enabled", "hasApiKey", "reachable"):
        assert key in body
    assert body["configured"] is True
    assert body["enabled"] is True
    assert body["hasApiKey"] is True
    assert body["reachable"] is True
    assert body["serverAuthMode"] == "bearer"
    assert body["serverVersion"] == "1.0"


def test_status_not_configured_skips_probe(monkeypatch) -> None:
    monkeypatch.setattr(
        external_service_routes,
        "load_service_settings",
        lambda spec: {"enabled": False, "baseUrl": "", "apiKey": ""},
    )
    calls = []

    async def fake_probe(values):
        calls.append(values)
        return {"reachable": True}

    body = _client(_spec("idle", fake_probe)).get("/api/v1/idle/status").json()

    assert body["configured"] is False
    assert body["reachable"] is False
    assert body["reason"] == "not_configured"
    assert calls == []


def test_probe_failure_is_reported_not_raised(monkeypatch) -> None:
    monkeypatch.setattr(
        external_service_routes,
        "load_service_settings",
        lambda spec: {"baseUrl": "http://demo3", "apiKey": ""},
    )

    async def boom(values):
        raise RuntimeError("connection refused")

    response = _client(_spec("demo3", boom)).get("/api/v1/demo3/status")
    body = response.json()

    assert response.status_code == 200
    assert body["configured"] is True
    assert body["reachable"] is False
    assert "connection refused" in body["error"]
