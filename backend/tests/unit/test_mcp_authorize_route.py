"""r64 — POST /mcp/servers/{name}/authorize 授权收口路由单测。

respx 假发现/注册/令牌端点 + monkeypatch webbrowser.open + 线程内真
GET 打进 loopback（r63 全链路测试同款），走 TestClient 验证路由层。
"""

from __future__ import annotations

import json
import pathlib
import threading
import urllib.parse
import urllib.request

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from backend.api import mcp_routes
from backend.mcp.oauth_store import OAuthTokenStore
from backend.mcp.pool import reset_pool

pytestmark = pytest.mark.unit

DIM = "https://auth.example.com"
SERVER_URL = "https://mcp.example.com/mcp"


@pytest.fixture()
def _isolated_pool(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path))
    reset_pool(None)
    yield
    reset_pool(None)


def _client(store):
    app = FastAPI()
    app.include_router(mcp_routes.router, prefix="/api/v1")
    return TestClient(app), store


def _seed_config_file(tmp_path: pathlib.Path, entry: dict) -> None:
    """写用户配置文件——路由 ensure_synced 自然加载（比 sync_configs 直注稳，
    避免与 _initial_sync_done 标志竞态）。"""
    (tmp_path / "mcp_servers.json").write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "command": "",
                        "args": [],
                        "env": {},
                        "enabled": True,
                        "required": False,
                        "timeout_seconds": 30,
                        **entry,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _auth_endpoints_mock(request: httpx.Request) -> Response:
    """发现 + 注册 + 令牌三端点（与 r63 全链路同款）。"""
    url = str(request.url)
    if "oauth-protected-resource" in url:
        return Response(
            200,
            json={
                "resource": SERVER_URL,
                "authorization_servers": [DIM],
            },
        )
    if "oauth-authorization-server" in url:
        return Response(
            200,
            json={
                "issuer": DIM,
                "authorization_endpoint": f"{DIM}/authorize",
                "token_endpoint": f"{DIM}/token",
                "registration_endpoint": f"{DIM}/register",
            },
        )
    if url.endswith("/register"):
        return Response(200, json={"client_id": "cid-r64"})
    if url.endswith("/token"):
        return Response(
            200,
            json={"access_token": "at-r64", "token_type": "Bearer", "expires_in": 600},
        )
    return Response(404, text="not found")


def test_authorize_success_roundtrip(_isolated_pool, tmp_path, monkeypatch):
    store = OAuthTokenStore(root=tmp_path)
    client, _ = _client(store)
    _seed_config_file(tmp_path, {"name": "oauth-srv", "url": SERVER_URL})

    with respx.mock(assert_all_called=False) as mock:
        mock.route().mock(side_effect=_auth_endpoints_mock)

        def fake_open(url):
            state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
            redirect = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)[
                "redirect_uri"
            ][0]

            def hit():
                urllib.request.urlopen(f"{redirect}?code=cb&state={state}", timeout=5).read()

            threading.Thread(target=hit).start()
            return True

        monkeypatch.setattr("webbrowser.open", fake_open)
        resp = client.post("/api/v1/mcp/servers/oauth-srv/authorize")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["server"] == "oauth-srv"
    assert body["token_type"] == "Bearer"
    assert body["expires_at"] > 0
    # token 入库（切片 2 注入链路数据源），但响应不回传 token 本体
    assert "access_token" not in body
    assert store.load("oauth-srv").access_token == "at-r64"


def test_authorize_stdio_server_400(_isolated_pool, tmp_path):
    store = OAuthTokenStore(root=tmp_path / "ud")
    client, _ = _client(store)

    _seed_config_file(tmp_path, {"name": "stdio-srv", "command": "node", "url": None})
    resp = client.post("/api/v1/mcp/servers/stdio-srv/authorize")
    assert resp.status_code == 400
    assert "stdio" in resp.json()["error"]


def test_authorize_unknown_server_404(_isolated_pool, tmp_path):
    client, _ = _client(OAuthTokenStore(root=tmp_path / "ud"))
    resp = client.post("/api/v1/mcp/servers/ghost/authorize")
    assert resp.status_code == 404
