"""M3 — MCP management REST API contract tests.

Uses the real FastAPI app with an isolated pool (fake client factory)
and a per-test SAGE_USER_DATA_DIR so config persistence never touches
real user data.
"""

import json

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.mcp import pool as pool_mod
from backend.mcp.pool import McpServerPool, reset_pool


class FakeMcpClient:
    """Minimal in-process client: every server comes up with one tool."""

    def __init__(self, config):
        self.config = config
        self._running = False

    def start(self):
        self._running = True

    def list_tools(self):
        return [
            {
                "name": "echo",
                "description": "echo",
                "inputSchema": {"type": "object"},
            }
        ]

    def call_tool(self, name, arguments):
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

    @property
    def is_running(self):
        return self._running

    def stop(self):
        self._running = False


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path))
    reset_pool(McpServerPool(client_factory=FakeMcpClient))
    yield TestClient(app)
    reset_pool(None)


def _config_path(tmp_path):
    return tmp_path / "mcp_servers.json"


class TestStatus:
    def test_status_always_200_with_contract_fields(self, client):
        resp = client.get("/api/v1/mcp/status")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {
            "generated_at",
            "all_ready",
            "degraded",
            "failed_required",
            "servers",
        }
        assert body["servers"] == []
        assert body["all_ready"] is True

    def test_status_reflects_added_server_state(self, client):
        client.post(
            "/api/v1/mcp/servers",
            json={"name": "srv", "command": "node"},
        )
        body = client.get("/api/v1/mcp/status").json()
        (entry,) = body["servers"]
        assert entry["name"] == "srv"
        assert entry["state"] == "ready"
        assert entry["tool_count"] == 1
        assert entry["required"] is False
        assert "since" in entry
        assert entry["last_error"] is None


class TestServerList:
    def test_env_secrets_redacted(self, client):
        client.post(
            "/api/v1/mcp/servers",
            json={
                "name": "srv",
                "command": "node",
                "env": {
                    "API_TOKEN": "super-secret",
                    "aws_secret_access": "shh",
                    "MY_PASSWORD": "hunter2",
                    "PRIVATE_KEY": "key-material",
                    "DRAWIO_BASE_URL": "http://localhost:8080",
                },
            },
        )
        body = client.get("/api/v1/mcp/servers").json()
        env = body["servers"][0]["env"]
        assert env["API_TOKEN"] == "***"
        assert env["aws_secret_access"] == "***"
        assert env["MY_PASSWORD"] == "***"
        assert env["PRIVATE_KEY"] == "***"
        assert env["DRAWIO_BASE_URL"] == "http://localhost:8080"

    def test_redaction_covers_all_secret_markers(self, client):
        # MEDIUM-4: auth/credential/pat/private markers redact too
        client.post(
            "/api/v1/mcp/servers",
            json={
                "name": "srv",
                "command": "node",
                "env": {
                    "API_TOKEN": "t",
                    "PRIVATE_KEY": "k",
                    "GH_PAT": "p",
                    "AUTH_HEADER": "a",
                    "CREDENTIAL": "c",
                    "AWS_CLIENT_SECRET": "s",
                    "MY_PASSWORD": "pw",
                    "DRAWIO_BASE_URL": "http://localhost:8080",
                },
            },
        )
        env = client.get("/api/v1/mcp/servers").json()["servers"][0]["env"]
        for secret_key in (
            "API_TOKEN",
            "PRIVATE_KEY",
            "GH_PAT",
            "AUTH_HEADER",
            "CREDENTIAL",
            "AWS_CLIENT_SECRET",
            "MY_PASSWORD",
        ):
            assert env[secret_key] == "***", secret_key
        assert env["DRAWIO_BASE_URL"] == "http://localhost:8080"

    def test_list_returns_full_config_shape(self, client):
        client.post(
            "/api/v1/mcp/servers",
            json={"name": "srv", "command": "node", "args": ["a.js"], "required": True},
        )
        (srv,) = client.get("/api/v1/mcp/servers").json()["servers"]
        assert srv["name"] == "srv"
        assert srv["command"] == "node"
        assert srv["args"] == ["a.js"]
        assert srv["required"] is True
        assert srv["enabled"] is True
        assert srv["timeout_seconds"] == 30.0
        assert srv["builtin"] is False  # user-added server


class TestAddServer:
    def test_add_valid_persists_and_discovers(self, client, tmp_path):
        resp = client.post(
            "/api/v1/mcp/servers",
            json={"name": "srv", "command": "node", "args": ["x.js"]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "name": "srv", "state": "ready"}
        stored = json.loads(_config_path(tmp_path).read_text(encoding="utf-8"))
        assert [s["name"] for s in stored["servers"]] == ["srv"]

    @pytest.mark.parametrize("bad_name", ["UPPER", "bad name"])
    def test_add_invalid_name_slug_400(self, client, bad_name):
        # passes pydantic shape checks, fails the slug regex → semantic 400
        resp = client.post(
            "/api/v1/mcp/servers", json={"name": bad_name, "command": "node"}
        )
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_add_overlong_name_422(self, client):
        # schema-level violation (max_length) → FastAPI 422
        resp = client.post(
            "/api/v1/mcp/servers", json={"name": "x" * 65, "command": "node"}
        )
        assert resp.status_code == 422

    def test_add_duplicate_name_400(self, client):
        client.post("/api/v1/mcp/servers", json={"name": "srv", "command": "node"})
        resp = client.post(
            "/api/v1/mcp/servers", json={"name": "srv", "command": "node"}
        )
        assert resp.status_code == 400
        assert "已存在" in resp.json()["error"]

    def test_add_extra_field_rejected(self, client):
        resp = client.post(
            "/api/v1/mcp/servers",
            json={"name": "srv", "command": "node", "bogus_field": 1},
        )
        assert resp.status_code == 422  # pydantic extra=forbid

    def test_add_disabled_server_state_disabled(self, client):
        resp = client.post(
            "/api/v1/mcp/servers",
            json={"name": "srv", "command": "node", "enabled": False},
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "disabled"


class TestUpdateServer:
    def test_disable_then_enable_round_trip(self, client, tmp_path):
        client.post("/api/v1/mcp/servers", json={"name": "srv", "command": "node"})
        resp = client.patch("/api/v1/mcp/servers/srv", json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json()["state"] == "disabled"
        stored = json.loads(_config_path(tmp_path).read_text(encoding="utf-8"))
        assert stored["servers"][0]["enabled"] is False

        resp = client.patch("/api/v1/mcp/servers/srv", json={"enabled": True})
        assert resp.json()["state"] == "ready"  # re-discovered on enable

    def test_update_timeout(self, client, tmp_path):
        client.post("/api/v1/mcp/servers", json={"name": "srv", "command": "node"})
        resp = client.patch("/api/v1/mcp/servers/srv", json={"timeout_seconds": 99})
        assert resp.status_code == 200
        stored = json.loads(_config_path(tmp_path).read_text(encoding="utf-8"))
        assert stored["servers"][0]["timeout_seconds"] == 99.0

    def test_update_timeout_on_running_server_triggers_rediscovery(
        self, tmp_path, monkeypatch
    ):
        # MEDIUM-5: the new timeout is baked into a fresh client — the
        # running server must be re-discovered, not silently left on the
        # old value.
        monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path))
        created = []

        def counting_factory(config):
            fake = FakeMcpClient(config)
            created.append(fake)
            return fake

        reset_pool(McpServerPool(client_factory=counting_factory))
        try:
            tc = TestClient(app)
            tc.post("/api/v1/mcp/servers", json={"name": "srv", "command": "node"})
            assert len(created) == 1

            resp = tc.patch("/api/v1/mcp/servers/srv", json={"timeout_seconds": 55})
            assert resp.status_code == 200
            assert resp.json()["state"] == "ready"
            assert len(created) == 2  # factory invoked again → re-discovery
        finally:
            reset_pool(None)

    def test_update_unknown_404(self, client):
        resp = client.patch("/api/v1/mcp/servers/ghost", json={"enabled": False})
        assert resp.status_code == 404

    def test_update_invalid_timeout_422(self, client):
        client.post("/api/v1/mcp/servers", json={"name": "srv", "command": "node"})
        resp = client.patch("/api/v1/mcp/servers/srv", json={"timeout_seconds": -1})
        assert resp.status_code == 422


class TestDeleteServer:
    def test_delete_user_server(self, client, tmp_path):
        client.post("/api/v1/mcp/servers", json={"name": "srv", "command": "node"})
        resp = client.delete("/api/v1/mcp/servers/srv")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "name": "srv"}
        stored = json.loads(_config_path(tmp_path).read_text(encoding="utf-8"))
        assert stored["servers"] == []
        assert client.get("/api/v1/mcp/servers").json()["servers"] == []

    def test_delete_builtin_rejected_400(self, client, monkeypatch):
        # simulate a built-in server present in the merged view
        from backend.mcp.config import validate_server_config

        builtin = validate_server_config(name="drawio", command="node")
        monkeypatch.setattr(pool_mod, "builtin_names", lambda: ["drawio"])
        pool = pool_mod.get_pool()
        pool.sync_configs([builtin])

        resp = client.delete("/api/v1/mcp/servers/drawio")
        assert resp.status_code == 400
        assert "内置" in resp.json()["error"]

    def test_delete_unknown_404(self, client):
        resp = client.delete("/api/v1/mcp/servers/ghost")
        assert resp.status_code == 404
