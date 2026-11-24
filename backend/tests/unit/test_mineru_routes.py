from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import mineru_routes
from backend.domain.document_parse import MineruSettings


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(mineru_routes.router, prefix="/api/v1")
    return app


def test_status_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(mineru_routes, "load_mineru_settings", lambda: MineruSettings())
    body = TestClient(_app()).get("/api/v1/mineru/status").json()
    assert body["configured"] is False
    assert body["hasApiKey"] is False
    assert body["reason"] == "not_configured"
    assert "apiKey" not in body


def test_status_probes_without_leaking_key(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def probe(self):
            return {
                "reachable": True,
                "serverAuthMode": "anonymous",
                "serverTiers": ["flash", "standard"],
                "serverVersion": "4.1.7",
                "reason": "",
                "accessLevel": "anonymous",
            }

    monkeypatch.setattr(
        mineru_routes,
        "load_mineru_settings",
        lambda: MineruSettings(
            enabled=True, base_url="http://m:8000", api_key="sk-synthetic"
        ),
    )
    monkeypatch.setattr(mineru_routes, "MineruClient", FakeClient)
    response = TestClient(_app()).get("/api/v1/mineru/status")
    assert "sk-synthetic" not in response.text
    body = response.json()
    assert body["hasApiKey"] is True
    assert body["reachable"] is True
    assert body["serverTiers"] == ["flash", "standard"]
