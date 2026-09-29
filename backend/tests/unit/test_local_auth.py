"""Tests for process-local capability authentication."""

import logging

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.api.local_auth import (
    LocalAuthMiddleware,
    initialize_local_auth_token,
    require_local_auth,
)


def _app_with_routes(*paths: str) -> FastAPI:
    """Build an app whose routes are guarded by the real middleware."""
    app = FastAPI()
    for path in paths:
        app.get(path, dependencies=[Depends(require_local_auth)])(lambda: {"ok": True})
    app.add_middleware(LocalAuthMiddleware)
    return app


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


def test_llm_proxy_path_uses_capability_header_over_provider_key(monkeypatch):
    """LLM 代理路由的 Authorization 装的是用户 provider key，须走兼容头。

    回归护栏：``is_local_auth_valid`` 对 ``/api/v1/llm/`` 前缀改用 Electron 的
    capability 兼容头。若这层豁免被删/改窄，provider key 会被当 capability 比对，
    端点「测试连接」恒 401「本地授权凭据无效或缺失」。

    覆盖全部四个内置 provider 经 providerRegistry 实际发出的路径。
    """
    token = "synthetic-local-capability"
    monkeypatch.setenv("SAGE_LOCAL_AUTH_TOKEN", token)
    initialize_local_auth_token()
    paths = (
        "/api/v1/llm/v1/models",  # openai-compatible / anthropic
        "/api/v1/llm/v1/chat/completions",
        "/api/v1/llm/v1/messages",
        "/api/v1/llm/v1beta/models",  # gemini
        "/api/v1/llm/v1beta/models/test-model:generateContent",
        "/api/v1/llm/api/tags",  # ollama
        "/api/v1/llm/api/chat",
    )
    client = TestClient(_app_with_routes(*paths))

    for path in paths:
        response = client.get(
            path,
            headers={
                "Authorization": "Bearer sk-provider-key-not-a-capability",
                "X-Sage-Local-Authorization": f"Bearer {token}",
            },
        )
        assert response.status_code == 200, path


def test_non_llm_path_still_rejects_provider_key(monkeypatch):
    """豁免必须限定在 LLM 代理路径,不得放宽到全站。"""
    token = "synthetic-local-capability"
    monkeypatch.setenv("SAGE_LOCAL_AUTH_TOKEN", token)
    initialize_local_auth_token()
    client = TestClient(_app_with_routes("/api/v1/agents"))

    response = client.get(
        "/api/v1/agents",
        headers={
            "Authorization": "Bearer sk-provider-key-not-a-capability",
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
