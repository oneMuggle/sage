"""Tests for GET /api/v1/arena/capabilities and /config (plan §4 D9).

These endpoints exist so the UI can explain *why* an arena feature is
unavailable instead of showing a bare 403/503. They must therefore answer 200
even when the feature is disabled or the service was never initialized, and
they must never leak secrets.
"""

import contextlib
import os
import tempfile

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import arena_routes
from backend.api.arena_routes import (
    init_arena_service,
    router,
    shutdown_arena_service,
)
from backend.config.arena_automation import ArenaAutomationConfig


@pytest.fixture()
def db_path():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    yield path
    shutdown_arena_service()
    arena_routes._config = None
    arena_routes._config_path = None
    arena_routes._db_path = None
    with contextlib.suppress(PermissionError):
        os.unlink(path)


def _client(config, path):
    init_arena_service(
        db_path=path,
        encryption_key=Fernet.generate_key(),
        config=config,
        config_path="backend/config/arena_automation.yaml",
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_capabilities_reports_disabled_flags(db_path):
    client = _client(ArenaAutomationConfig(enabled=False), db_path)
    response = client.get("/api/v1/arena/capabilities")
    assert response.status_code == 200  # diagnostics work even when disabled
    body = response.json()
    assert body["initialized"] is True
    assert body["enabled"] is False
    assert body["flags"] == {
        "registration": False,
        "draw": False,
        "proxy": False,
        "token_window": False,
    }
    assert body["config_path"].endswith("arena_automation.yaml")
    assert body["http"]["default_backend"] == "httpx"  # S0 measurement
    assert body["mail"]["configured"] == "tenminmail"
    assert "tenminmail" in body["mail"]["available"]
    assert body["token_window"]["available"] is False  # lands in P3
    assert body["browser_path"]["available"] is True
    assert body["data"]["credentials_readable"] is True
    assert body["data"]["accounts_total"] == 0
    # account endpoints stay gated
    assert client.get("/api/v1/arena/accounts").status_code == 403


def test_capabilities_reflects_sub_flags(db_path):
    config = ArenaAutomationConfig(enabled=True)
    config.registration.enabled = True
    config.draw.enabled = True
    body = _client(config, db_path).get("/api/v1/arena/capabilities").json()
    assert body["flags"] == {
        "registration": True,
        "draw": True,
        "proxy": False,
        "token_window": False,
    }


def test_sub_flag_cannot_enable_without_master_switch(db_path):
    config = ArenaAutomationConfig(enabled=False)
    config.registration.enabled = True
    config.draw.enabled = True
    body = _client(config, db_path).get("/api/v1/arena/capabilities").json()
    assert body["enabled"] is False
    assert body["flags"]["registration"] is False
    assert body["flags"]["draw"] is False


def test_capabilities_works_without_initialized_service(db_path):
    shutdown_arena_service()
    arena_routes._config = None
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/api/v1/arena/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["initialized"] is False
    assert body["enabled"] is False
    assert body["data"]["credentials_readable"] is None
    assert client.get("/api/v1/arena/accounts").status_code == 503


def test_capabilities_flags_unreadable_credentials(db_path):
    """master.key lost / machine changed → UI must be told, not crash."""
    config = ArenaAutomationConfig(enabled=True)
    service = init_arena_service(
        db_path=db_path, encryption_key=Fernet.generate_key(), config=config
    )
    service.create_account(email="k@example.com", password="p")
    # Re-open the same DB with a different key (simulates a lost master.key).
    init_arena_service(
        db_path=db_path, encryption_key=Fernet.generate_key(), config=config
    )
    app = FastAPI()
    app.include_router(router)
    body = TestClient(app).get("/api/v1/arena/capabilities").json()
    assert body["data"]["credentials_readable"] is False
    assert body["data"]["accounts_total"] == 1
    # The list endpoint still answers so the UI can show the pool.
    listing = TestClient(app).get("/api/v1/arena/accounts")
    assert listing.status_code == 200


def test_config_endpoint_redacts_secrets(db_path):
    config = ArenaAutomationConfig(enabled=True)
    config.proxy.api_token = "super-secret-token"
    config.proxy.pool_text = "user:pass@1.2.3.4:8080"
    config.mail_api_key = "mail-key"
    client = _client(config, db_path)
    response = client.get("/api/v1/arena/config")
    assert response.status_code == 200
    body = response.json()
    assert body["proxy"]["api_token"] == "***redacted***"
    assert body["proxy"]["pool_text"] == "***redacted***"
    assert body["mail_api_key"] == "***redacted***"
    assert "super-secret-token" not in response.text
    assert "mail-key" not in response.text
    assert body["draw"]["miss_action"] == "archive"
    assert body["registration"]["concurrency"] == 3


def test_config_endpoint_403_when_disabled(db_path):
    client = _client(ArenaAutomationConfig(enabled=False), db_path)
    assert client.get("/api/v1/arena/config").status_code == 403
