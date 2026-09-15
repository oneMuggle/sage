"""Tests for process-local capability authentication."""

import logging

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.api.local_auth import initialize_local_auth_token, require_local_auth


@pytest.fixture()
def auth_app(monkeypatch):
    token = "synthetic-local-capability"
    monkeypatch.setenv("SAGE_LOCAL_AUTH_TOKEN", token)
    initialize_local_auth_token()
    app = FastAPI()

    @app.get("/protected", dependencies=[Depends(require_local_auth)])
    def protected():
        return {"ok": True}

    return app, token


def test_missing_and_invalid_bearer_are_rejected(auth_app):
    app, _ = auth_app
    client = TestClient(app)

    assert client.get("/protected").status_code == 401
    assert client.get("/protected", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_valid_bearer_is_accepted(auth_app):
    app, token = auth_app
    response = TestClient(app).get(
        "/protected", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_explicit_empty_authorization_overrides_compatibility_header(auth_app):
    app, token = auth_app
    response = TestClient(app).get(
        "/protected",
        headers={
            "Authorization": "",
            "X-Sage-Local-Authorization": f"Bearer {token}",
        },
    )

    assert response.status_code == 401


def test_capability_is_not_logged(caplog, monkeypatch):
    token = "synthetic-secret-that-must-not-leak"
    monkeypatch.setenv("SAGE_LOCAL_AUTH_TOKEN", token)
    with caplog.at_level(logging.DEBUG):
        initialize_local_auth_token()

    assert token not in caplog.text
