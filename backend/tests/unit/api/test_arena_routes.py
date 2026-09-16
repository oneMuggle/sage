import os
import tempfile

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.arena_routes import router, init_arena_service
from backend.config.arena_automation import ArenaAutomationConfig


@pytest.fixture
def client():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    key = Fernet.generate_key()
    cfg = ArenaAutomationConfig(enabled=True)
    init_arena_service(db_path=path, encryption_key=key, config=cfg)
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    os.unlink(path)


@pytest.fixture
def disabled_client():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    key = Fernet.generate_key()
    cfg = ArenaAutomationConfig(enabled=False)
    init_arena_service(db_path=path, encryption_key=key, config=cfg)
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    os.unlink(path)


def test_create_and_list_accounts(client):
    r = client.post(
        "/api/v1/arena/accounts",
        json={"email": "x@example.com", "password": "p"},
    )
    assert r.status_code == 201
    acc = r.json()
    assert acc["email"] == "x@example.com"
    # List
    r2 = client.get("/api/v1/arena/accounts")
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_get_account_returns_decrypted(client):
    r = client.post(
        "/api/v1/arena/accounts",
        json={"email": "y@example.com", "password": "secret"},
    )
    acc_id = r.json()["id"]
    r2 = client.get(f"/api/v1/arena/accounts/{acc_id}")
    assert r2.status_code == 200
    assert r2.json()["password"] == "secret"


def test_soft_delete_account(client):
    r = client.post(
        "/api/v1/arena/accounts",
        json={"email": "z@example.com", "password": "p"},
    )
    acc_id = r.json()["id"]
    r2 = client.delete(f"/api/v1/arena/accounts/{acc_id}")
    assert r2.status_code == 204
    r3 = client.get(f"/api/v1/arena/accounts/{acc_id}")
    assert r3.json()["state"] == "destroyed"


def test_endpoints_return_403_when_disabled(disabled_client):
    r = disabled_client.post(
        "/api/v1/arena/accounts",
        json={"email": "x@example.com", "password": "p"},
    )
    assert r.status_code == 403
    r2 = disabled_client.get("/api/v1/arena/accounts")
    assert r2.status_code == 403


def test_enable_account_resets_state(client):
    r = client.post(
        "/api/v1/arena/accounts",
        json={"email": "e@example.com", "password": "p"},
    )
    acc_id = r.json()["id"]
    # Disable via isolate
    client.post(f"/api/v1/arena/accounts/{acc_id}/isolate")
    r2 = client.post(f"/api/v1/arena/accounts/{acc_id}/enable")
    assert r2.status_code == 200
    r3 = client.get(f"/api/v1/arena/accounts/{acc_id}")
    assert r3.json()["state"] == "available"
