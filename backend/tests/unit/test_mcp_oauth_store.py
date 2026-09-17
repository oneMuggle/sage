"""r61 — MCP OAuth 切片 2 单测：token 存储 / 过期刷新 / http_client 注入。"""

import httpx
import pytest

from backend.mcp.config import validate_server_config
from backend.mcp.http_client import HttpClientMcpClient
from backend.mcp.oauth import build_refresh_request, is_token_expired
from backend.mcp.oauth_store import OAuthTokenStore, TokenRecord

pytestmark = pytest.mark.unit


def _record(**overrides) -> TokenRecord:
    defaults = {
        "server_name": "srv",
        "access_token": "at-1",
        "token_type": "Bearer",
        "expires_at": 0.0,
        "refresh_token": "rt-1",
        "client_id": "sage",
        "token_endpoint": "https://auth.example.com/token",
    }
    defaults.update(overrides)
    return TokenRecord(**defaults)


class TestTokenStore:
    def test_roundtrip(self, tmp_path):
        store = OAuthTokenStore(root=tmp_path)
        store.save(_record())
        loaded = store.load("srv")
        assert loaded is not None
        assert loaded.access_token == "at-1"
        assert loaded.refresh_token == "rt-1"

    def test_missing_returns_none(self, tmp_path):
        assert OAuthTokenStore(root=tmp_path).load("ghost") is None

    def test_delete(self, tmp_path):
        store = OAuthTokenStore(root=tmp_path)
        store.save(_record())
        assert store.delete("srv") is True
        assert store.delete("srv") is False
        assert store.load("srv") is None

    def test_corrupt_file_treated_as_empty(self, tmp_path):
        root = tmp_path / "ud"
        root.mkdir()
        (root / "mcp_oauth_tokens.json").write_text("not-json", encoding="utf-8")
        store = OAuthTokenStore(root=root)
        assert store.load("srv") is None
        # 写入自愈
        store.save(_record())
        assert store.load("srv") is not None

    def test_invalid_entries_skipped(self, tmp_path):
        store = OAuthTokenStore(root=tmp_path)
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text(
            '{"a": {"server_name": "a", "access_token": "t"}, "b": "junk", "c": {}}',
            encoding="utf-8",
        )
        assert store.load("a") is not None
        assert store.load("b") is None
        assert store.load("c") is None


class TestExpiryAndRefreshRequest:
    def test_no_expiry_means_never_expired(self):
        assert is_token_expired(_record(expires_at=0.0), now=10**12) is False

    def test_expired_past(self):
        assert is_token_expired(_record(expires_at=1000.0), now=2000.0) is True

    def test_skew_treats_soon_expiry_as_expired(self):
        # 剩余 30s < 60s skew
        assert is_token_expired(_record(expires_at=1030.0), now=1000.0) is True
        # 剩余 120s > skew
        assert is_token_expired(_record(expires_at=1120.0), now=1000.0) is False

    def test_refresh_request_shape(self):
        url, headers, body = build_refresh_request(
            "https://auth.example.com/token", "sage", "rt-1", scope="mcp:tools"
        )
        assert url == "https://auth.example.com/token"
        assert headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert "grant_type=refresh_token" in body
        assert "refresh_token=rt-1" in body
        assert "client_id=sage" in body
        assert "scope=mcp%3Atools" in body

    @pytest.mark.parametrize("missing", ["token_endpoint", "client_id", "refresh_token"])
    def test_refresh_request_requires_fields(self, missing):
        kwargs = {
            "token_endpoint": "https://a/t",
            "client_id": "sage",
            "refresh_token": "rt",
        }
        kwargs.pop(missing)
        empty = {"token_endpoint": "", "client_id": "", "refresh_token": ""}
        args = {**kwargs}
        with pytest.raises(Exception, match="不能为空"):
            build_refresh_request(
                args.get("token_endpoint", empty["token_endpoint"]),
                args.get("client_id", empty["client_id"]),
                args.get("refresh_token", empty["refresh_token"]),
            )


class TestHttpClientInjection:
    def _make_client(self, tmp_path, store):
        config = validate_server_config("srv", url="https://mcp.example.com/rpc", timeout_seconds=5)
        return HttpClientMcpClient(config, oauth_store=store)

    def _start_transport(self, captured):
        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "x"}}},
                headers={"mcp-session-id": "sess-1"},
            )

        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_no_token_no_auth_header(self, tmp_path):
        captured: list = []
        client = self._make_client(tmp_path, OAuthTokenStore(root=tmp_path / "empty"))
        client._client = self._start_transport(captured)
        client.start()
        assert captured
        assert "authorization" not in {k.lower() for k in captured[0].headers}

    def test_valid_token_injected(self, tmp_path):
        store = OAuthTokenStore(root=tmp_path)
        store.save(_record(expires_at=0.0))
        captured: list = []
        client = self._make_client(tmp_path, store)
        client._client = self._start_transport(captured)
        client.start()
        auth = [v for k, v in captured[0].headers.items() if k.lower() == "authorization"]
        assert auth == ["Bearer at-1"]

    def test_oauth_overrides_static_authorization(self, tmp_path):
        store = OAuthTokenStore(root=tmp_path)
        store.save(_record(expires_at=0.0))
        captured: list = []
        config = validate_server_config("srv", url="https://mcp.example.com/rpc", timeout_seconds=5)
        config.headers["Authorization"] = "Bearer static-pat"
        client = HttpClientMcpClient(config, oauth_store=store)
        client._client = self._start_transport(captured)
        client.start()
        auth = [v for k, v in captured[0].headers.items() if k.lower() == "authorization"]
        assert auth == ["Bearer at-1"]

    def test_expired_token_refreshed_and_injected(self, tmp_path):
        store = OAuthTokenStore(root=tmp_path)
        store.save(_record(expires_at=1000.0, refresh_token="rt-1"))  # 已过期

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "auth.example.com":
                return httpx.Response(
                    200,
                    json={"access_token": "at-2", "token_type": "Bearer", "expires_in": 3600},
                )
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "x"}}},
            )

        client = self._make_client(tmp_path, store)
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        client.start()
        assert store.load("srv").access_token == "at-2"

    def test_refresh_failure_fail_open(self, tmp_path):
        store = OAuthTokenStore(root=tmp_path)
        store.save(_record(expires_at=1000.0, refresh_token="rt-1"))

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "auth.example.com":
                return httpx.Response(500, text="boom")
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "x"}}},
            )

        client = self._make_client(tmp_path, store)
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        client.start()  # 刷新失败不应抛出
        assert store.load("srv") is None  # 记录被清除
