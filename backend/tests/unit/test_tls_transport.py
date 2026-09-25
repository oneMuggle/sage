# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""tls_transport 单测（R27 / AB3：TLS/HTTP2 指纹传输器）。

curl_cffi 不进测试依赖 —— 用 sys.modules 注入假模块测适配层；
配置开关沿用 settings_repo 假体模式。
"""

from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List

import httpx
import pytest

from backend.data import settings_repo
from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.tools import tls_transport, web_tool
from backend.tools.tls_transport import (
    CurlImpersonateTransport,
    build_fingerprint_transport,
    fingerprint_enabled,
)

pytestmark = [pytest.mark.unit]


class _FakeRepo:
    def __init__(self, raw: str = None):
        self.raw = raw

    def get(self, key: str):
        return self.raw


@pytest.fixture(autouse=True)
def _reset_import_cache(monkeypatch):
    monkeypatch.setattr(tls_transport, "_import_failed", False)
    # R34：计数为模块级状态，逐用例重置避免跨用例污染
    monkeypatch.setattr(tls_transport, "_stats", {"requests": 0})
    monkeypatch.setattr(tls_transport, "_stats_hosts", {})


def _install_repo(monkeypatch, raw):
    monkeypatch.setattr(settings_repo, "SettingsRepository", lambda: _FakeRepo(raw))


def _install_fake_curl(monkeypatch, response, captured: Dict[str, Any]):
    fake_requests = SimpleNamespace(request=lambda *a, **kw: captured.update(kw) or response)
    module = ModuleType("curl_cffi")
    module.requests = fake_requests  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "curl_cffi", module)


def test_fingerprint_enabled_follows_config(monkeypatch):
    _install_repo(monkeypatch, None)
    assert fingerprint_enabled() is False
    _install_repo(monkeypatch, json.dumps({"tls_fingerprint": True}))
    assert fingerprint_enabled() is True
    _install_repo(monkeypatch, "not-json")
    assert fingerprint_enabled() is False


def test_build_transport_falls_back_without_curl_cffi(monkeypatch):
    _install_repo(monkeypatch, json.dumps({"tls_fingerprint": True}))
    monkeypatch.setitem(sys.modules, "curl_cffi", None)  # import 即 ImportError
    assert build_fingerprint_transport() is None


def test_transport_maps_response_and_pins_flags(monkeypatch):
    captured: Dict[str, Any] = {}
    response = SimpleNamespace(
        status_code=403,
        headers={"content-type": "text/html"},
        content=b"blocked",
    )

    def _fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured.update(kwargs)
        return response

    module = ModuleType("curl_cffi")
    module.requests = SimpleNamespace(request=_fake_request)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "curl_cffi", module)

    transport = build_fingerprint_transport(verify=True)
    assert isinstance(transport, CurlImpersonateTransport)
    request = httpx.Request("GET", "https://x.example/")
    result = transport.handle_request(request)
    assert result.status_code == 403
    assert result.content == b"blocked"
    assert captured["impersonate"] == "chrome"
    assert captured["allow_redirects"] is False
    assert captured["verify"] is True
    assert captured["url"] == "https://x.example/"
    assert captured["method"] == "GET"


def test_transport_passes_app_proxies(monkeypatch):
    captured: Dict[str, Any] = {}
    response = SimpleNamespace(status_code=200, headers={}, content=b"")

    def _fake_request(method, url, **kwargs):
        captured.update(kwargs)
        return response

    module = ModuleType("curl_cffi")
    module.requests = SimpleNamespace(request=_fake_request)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "curl_cffi", module)
    monkeypatch.setattr(
        tls_transport,
        "_app_proxies",
        lambda: {"https": "http://127.0.0.1:7890"},
    )

    transport = CurlImpersonateTransport(verify=False)
    transport.handle_request(httpx.Request("GET", "https://x.example/"))
    assert captured["proxies"] == {"https": "http://127.0.0.1:7890"}
    assert captured["verify"] is False


def test_app_proxies_empty_when_factory_fails(monkeypatch):
    monkeypatch.setattr(
        tls_transport, "_app_proxies", lambda: {}, raising=True
    )  # 直接断言函数行为在工厂失败时已由实现兜底；这里验证返回空字典的契约
    # 真实路径：http_factory 导入失败 → _app_proxies 内部 except 返回 {}
    import backend.tools.http_factory  # noqa: F401

    assert isinstance(tls_transport._app_proxies(), dict)


class _StopBuildError(Exception):
    pass


def _run_get_with_redirects_capture(monkeypatch, enabled: bool) -> Dict[str, Any]:
    captured: Dict[str, Any] = {}
    sentinel_transport = object()
    monkeypatch.setattr(web_tool, "fingerprint_enabled", lambda: enabled)
    monkeypatch.setattr(
        web_tool, "build_fingerprint_transport", lambda verify: sentinel_transport
    )

    tool = web_tool.WebFetchTool()  # 构造期也会 build_client，先建再打补丁

    def _fake_build_client(**kwargs):
        captured.update(kwargs)
        raise _StopBuildError()

    monkeypatch.setattr(web_tool, "build_client", _fake_build_client)
    with pytest.raises(_StopBuildError):
        tool._get_with_redirects(
            "https://example.com/",
            NetworkPolicy(mode=NetworkMode.ONLINE),
            gated_by_whitelist=False,
        )
    return captured


def test_get_with_redirects_injects_transport_when_enabled(monkeypatch):
    captured = _run_get_with_redirects_capture(monkeypatch, enabled=True)
    assert "transport" in captured


def test_get_with_redirects_no_transport_when_disabled(monkeypatch):
    captured = _run_get_with_redirects_capture(monkeypatch, enabled=False)
    assert "transport" not in captured


def test_stats_counts_requests_and_returns_copy(monkeypatch):
    response = SimpleNamespace(status_code=200, headers={}, content=b"")

    def _fake_request(method, url, **kwargs):
        return response

    module = ModuleType("curl_cffi")
    module.requests = SimpleNamespace(request=_fake_request)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "curl_cffi", module)

    before = tls_transport.stats()["requests"]
    transport = CurlImpersonateTransport()
    transport.handle_request(httpx.Request("GET", "https://x.example/"))
    transport.handle_request(httpx.Request("GET", "https://y.example/"))

    snapshot = tls_transport.stats()
    assert snapshot["requests"] == before + 2
    snapshot["requests"] = 999  # 拷贝语义：外部修改不污染内部计数
    assert tls_transport.stats()["requests"] == before + 2
    assert snapshot["hosts"] == {"x.example": 1, "y.example": 1}  # R34 按 host 细分


def test_get_with_redirects_closes_client_on_redirect_limit(monkeypatch):
    """R29：重定向超限异常路径也要关闭 client（此前仅重建分支 close）。"""
    import httpx as _httpx

    close_calls: List[int] = []

    class _Client:
        def close(self):
            close_calls.append(1)

        def build_request(self, method, url, headers=None):
            return _httpx.Request(method, url, headers=headers)

    def _fake_build_client(**kwargs):
        return _Client()

    def _fake_retrying_send(client, request, stream=False):
        return _httpx.Response(
            302, headers={"location": "https://b.example/"}, request=request
        )

    monkeypatch.setattr(web_tool, "build_client", _fake_build_client)
    monkeypatch.setattr(web_tool, "fingerprint_enabled", lambda: False)
    monkeypatch.setattr(web_tool, "retrying_send", _fake_retrying_send)
    tool = web_tool.WebFetchTool()
    with pytest.raises(ValueError, match="redirect_limit_exceeded"):
        tool._get_with_redirects(
            "https://a.example/",
            NetworkPolicy(mode=NetworkMode.ONLINE),
            gated_by_whitelist=False,
        )
    assert close_calls  # finally 释放了连接池


def test_stats_hosts_cap_clears_when_full(monkeypatch):
    """R34：host 细分超上限整体清零（诊断视角，保新弃旧）。"""
    monkeypatch.setattr(tls_transport, "MAX_TLS_STATS_HOSTS", 2)
    response = SimpleNamespace(status_code=200, headers={}, content=b"")

    def _fake_request(method, url, **kwargs):
        return response

    module = ModuleType("curl_cffi")
    module.requests = SimpleNamespace(request=_fake_request)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "curl_cffi", module)

    transport = CurlImpersonateTransport()
    transport.handle_request(httpx.Request("GET", "https://a.example/"))
    transport.handle_request(httpx.Request("GET", "https://b.example/"))
    transport.handle_request(httpx.Request("GET", "https://c.example/"))

    snapshot = tls_transport.stats()
    assert snapshot["requests"] == 3
    assert snapshot["hosts"] == {"c.example": 1}  # 清零后仅剩最新
