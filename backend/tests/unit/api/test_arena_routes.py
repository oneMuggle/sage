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
    # password is stripped from API responses (VULN-01 fix)
    assert "password" not in r2.json()
    assert r2.json()["email"] == "y@example.com"


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


def test_get_service_raises_503_when_uninitialized():
    """Line 58: get_service() raises 503 if init_arena_service was never called."""
    import backend.api.arena_routes as routes_mod

    old_svc = routes_mod._service
    try:
        routes_mod._service = None
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as excinfo:
            routes_mod.get_service()
        assert excinfo.value.status_code == 503
    finally:
        routes_mod._service = old_svc


def test_max_accounts_returns_409():
    """Line 74: creating account beyond max_accounts limit returns 409."""
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    key = Fernet.generate_key()
    cfg = ArenaAutomationConfig(enabled=True, max_accounts=1)
    init_arena_service(db_path=path, encryption_key=key, config=cfg)
    app = FastAPI()
    app.include_router(router)
    tc = TestClient(app)
    try:
        r1 = tc.post(
            "/api/v1/arena/accounts",
            json={"email": "first@example.com", "password": "p"},
        )
        assert r1.status_code == 201
        r2 = tc.post(
            "/api/v1/arena/accounts",
            json={"email": "second@example.com", "password": "p"},
        )
        assert r2.status_code == 409
    finally:
        os.unlink(path)


def test_duplicate_email_returns_409(client):
    """Lines 80-81: duplicate email raises HTTPException 409."""
    client.post(
        "/api/v1/arena/accounts",
        json={"email": "dup@example.com", "password": "p"},
    )
    r = client.post(
        "/api/v1/arena/accounts",
        json={"email": "dup@example.com", "password": "p2"},
    )
    assert r.status_code == 409


def test_list_accounts_with_state_filter(client):
    """Lines 91-95: valid state filter returns filtered list."""
    client.post(
        "/api/v1/arena/accounts",
        json={"email": "s1@example.com", "password": "p"},
    )
    r = client.get("/api/v1/arena/accounts?state=available")
    assert r.status_code == 200
    # Invalid state returns 400
    r2 = client.get("/api/v1/arena/accounts?state=garbage")
    assert r2.status_code == 400


def test_get_nonexistent_account_returns_404(client):
    """Line 107: get_account returns 404 when id doesn't exist."""
    r = client.get("/api/v1/arena/accounts/nonexistent-id")
    assert r.status_code == 404


def test_delete_nonexistent_account_returns_404(client):
    """Line 118: soft_delete returns 404 when id doesn't exist."""
    r = client.delete("/api/v1/arena/accounts/nonexistent-id")
    assert r.status_code == 404


def test_isolate_nonexistent_account_returns_404(client):
    """Line 130: isolate returns 404 when id doesn't exist."""
    r = client.post("/api/v1/arena/accounts/nonexistent-id/isolate")
    assert r.status_code == 404


def test_enable_nonexistent_account_returns_404(client):
    """Line 145: enable returns 404 when id doesn't exist."""
    r = client.post("/api/v1/arena/accounts/nonexistent-id/enable")
    assert r.status_code == 404


def test_get_stats_endpoint(client):
    """Lines 155-159: stats endpoint returns state and failure count."""
    r1 = client.post(
        "/api/v1/arena/accounts",
        json={"email": "stats@example.com", "password": "p"},
    )
    acc_id = r1.json()["id"]
    r = client.get(f"/api/v1/arena/accounts/{acc_id}/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == acc_id
    assert body["state"] == "available"
    assert "failure_count" in body
    # nonexistent account returns 404
    r2 = client.get("/api/v1/arena/accounts/nonexistent-id/stats")
    assert r2.status_code == 404


def test_api_responses_never_leak_password(client):
    """VULN-01 regression: password must be stripped from every endpoint."""
    r1 = client.post(
        "/api/v1/arena/accounts",
        json={"email": "leak@example.com", "password": "sekret"},
    )
    assert "password" not in r1.json()
    acc_id = r1.json()["id"]
    # list
    r2 = client.get("/api/v1/arena/accounts")
    assert all("password" not in a for a in r2.json())
    # get
    r3 = client.get(f"/api/v1/arena/accounts/{acc_id}")
    assert "password" not in r3.json()
    # isolate
    r4 = client.post(f"/api/v1/arena/accounts/{acc_id}/isolate")
    assert "password" not in r4.json()
    # enable
    r5 = client.post(f"/api/v1/arena/accounts/{acc_id}/enable")
    assert "password" not in r5.json()
