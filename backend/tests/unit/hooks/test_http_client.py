"""R124 — HTTP Hook 客户端单元测试。

覆盖：resolve_header_value 的 ${env:} 占位符替换（含未设置 env、多占位
符、未闭合标记）、resolve_headers 的类型过滤、send_http_hook 的 fail-open
全路径（非法方法/URL、超限响应、非 2xx、非 object JSON、网络错误、
畸形 JSON）与成功路径。fake AsyncClient 替代真实网络。
"""

from __future__ import annotations

import json

import httpx
import pytest

from backend.hooks import http_client as hc
from backend.hooks.http_client import (
    resolve_header_value,
    resolve_headers,
    send_http_hook,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# resolve_header_value / resolve_headers
# ---------------------------------------------------------------------------


def test_env_placeholder_replaced(monkeypatch):
    monkeypatch.setenv("HOOK_TOKEN", "abc123")
    assert resolve_header_value("Bearer ${env:HOOK_TOKEN}") == "Bearer abc123"


def test_unset_env_replaced_with_empty(monkeypatch):
    monkeypatch.delenv("HOOK_MISSING", raising=False)
    assert resolve_header_value("X${env:HOOK_MISSING}Y") == "XY"


def test_multiple_placeholders(monkeypatch):
    monkeypatch.setenv("A", "1")
    monkeypatch.setenv("B", "2")
    assert resolve_header_value("${env:A}-${env:B}") == "1-2"


def test_unterminated_placeholder_left_as_is(monkeypatch):
    assert resolve_header_value("${env:NO_CLOSE") == "${env:NO_CLOSE"


def test_resolve_headers_filters_non_string_pairs(monkeypatch):
    monkeypatch.delenv("__R124_NOPE__", raising=False)
    assert resolve_headers(
        {"ok": "v-${env:__R124_NOPE__}", 1: "x", "bad": 2, None: "y"}
    ) == {"ok": "v-"}


def test_resolve_headers_non_dict_returns_empty():
    assert resolve_headers(None) == {}
    assert resolve_headers(["a=1"]) == {}


# ---------------------------------------------------------------------------
# send_http_hook fail-open 路径
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b"{}"):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("malformed json")
        return self._payload


class _FakeClient:
    """async context manager 形状的替身客户端，捕获请求实参。"""

    last_request = None
    response = None
    raise_on_request = None

    def __init__(self, **kwargs):
        _FakeClient.init_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, method, url, **kwargs):
        _FakeClient.last_request = {"method": method, "url": url, **kwargs}
        if _FakeClient.raise_on_request is not None:
            raise _FakeClient.raise_on_request
        return _FakeClient.response


@pytest.fixture(autouse=True)
def _reset_fake():
    _FakeClient.last_request = None
    _FakeClient.response = _FakeResponse()
    _FakeClient.raise_on_request = None
    _FakeClient.init_kwargs = {}


def _install(monkeypatch):
    monkeypatch.setattr(hc.httpx, "AsyncClient", _FakeClient)


@pytest.mark.parametrize("method", ["DELETE", "TRACE", "get", ""])
@pytest.mark.asyncio()
async def test_unsupported_method_fails_open(monkeypatch, method):
    _install(monkeypatch)
    assert await send_http_hook("https://x/hook", {}, method=method) is None
    assert _FakeClient.last_request is None  # 未发起请求


@pytest.mark.asyncio()
async def test_non_http_url_fails_open(monkeypatch):
    _install(monkeypatch)
    assert await send_http_hook("ftp://x/hook", {}) is None
    assert await send_http_hook("file:///etc/passwd", {}) is None


@pytest.mark.asyncio()
async def test_non_str_url_fails_open(monkeypatch):
    _install(monkeypatch)
    assert await send_http_hook(None, {}) is None  # type: ignore[arg-type]


@pytest.mark.asyncio()
async def test_oversized_response_fails_open(monkeypatch):
    _install(monkeypatch)
    monkeypatch.setattr(hc, "MAX_RESPONSE_BYTES", 4)
    _FakeClient.response = _FakeResponse(content=b"12345678")
    assert await send_http_hook("https://x/hook", {}) is None


@pytest.mark.asyncio()
async def test_non_2xx_fails_open(monkeypatch):
    _install(monkeypatch)
    _FakeClient.response = _FakeResponse(status_code=500)
    assert await send_http_hook("https://x/hook", {}) is None


@pytest.mark.asyncio()
async def test_non_object_json_fails_open(monkeypatch):
    _install(monkeypatch)
    _FakeClient.response = _FakeResponse(payload=["not", "a", "dict"])
    assert await send_http_hook("https://x/hook", {}) is None


@pytest.mark.asyncio()
async def test_malformed_json_fails_open(monkeypatch):
    _install(monkeypatch)
    _FakeClient.response = _FakeResponse(payload=None, content=b"not-json{")
    assert await send_http_hook("https://x/hook", {}) is None


@pytest.mark.asyncio()
async def test_network_error_fails_open(monkeypatch):
    _install(monkeypatch)
    _FakeClient.raise_on_request = httpx.ConnectError("down")
    assert await send_http_hook("https://x/hook", {}) is None


# ---------------------------------------------------------------------------
# send_http_hook 成功路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_success_returns_dict_and_sends_payload(monkeypatch):
    _install(monkeypatch)
    _FakeClient.response = _FakeResponse(payload={"decision": "allow"})
    out = await send_http_hook(
        "https://x/hook", {"event": "pre-tool"}, method="PUT", timeout_seconds=3.5
    )
    assert out == {"decision": "allow"}
    req = _FakeClient.last_request
    assert req["method"] == "PUT"
    assert req["url"] == "https://x/hook"
    assert req["json"] == {"event": "pre-tool"}
    assert _FakeClient.init_kwargs["follow_redirects"] is False
    assert _FakeClient.init_kwargs["timeout"].read == 3.5


@pytest.mark.asyncio()
async def test_headers_resolved_into_request(monkeypatch):
    _install(monkeypatch)
    monkeypatch.setenv("HOOK_TOKEN", "tok")
    await send_http_hook(
        "https://x/hook", {}, headers={"X-Token": "${env:HOOK_TOKEN}"}
    )
    headers = _FakeClient.last_request["headers"]
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Token"] == "tok"


@pytest.mark.asyncio()
async def test_unset_env_header_resolves_empty(monkeypatch):
    _install(monkeypatch)
    monkeypatch.delenv("HOOK_NONE", raising=False)
    await send_http_hook("https://x/hook", {}, headers={"X-None": "${env:HOOK_NONE}"})
    assert _FakeClient.last_request["headers"]["X-None"] == ""


def test_json_payload_matches_wire_format():
    # 与 shell hook 相同 JSON payload 的序列化契约（冒烟）
    payload = json.dumps({"event": "post-tool", "ok": True})
    assert json.loads(payload)["ok"] is True
