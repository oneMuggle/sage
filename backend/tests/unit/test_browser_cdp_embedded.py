"""Embedded（Electron 内置浏览器）后端接入测试。

覆盖：env 发现优先级、launch_browser 不 spawn 子进程、cdp_command HTTP 转发、
错误映射、渲染池事件通道跳过、健康检查展示。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.tools import browser_cdp, web_render
from backend.tools.browser_cdp import BrowserCDPError, BrowserSession, BrowserType
from backend.tools.browser_launcher import EmbeddedLauncher

pytestmark = pytest.mark.unit


def _embedded_session(headless: bool = True) -> BrowserSession:
    return BrowserSession(
        browser_id="emb",
        executable="(embedded)",
        headless=headless,
        user_data_dir="",
        process=browser_cdp._EmbeddedProcess(),
        port=43210,
        ws_path="/devtools/browser/embedded",
        persistent=True,
        profile_name="embedded",
        browser_type=BrowserType.EMBEDDED,
        bridge_token="tok-123",
    )


def test_discover_embedded_from_env(monkeypatch):
    monkeypatch.setenv("SAGE_EMBEDDED_BROWSER", "1")
    monkeypatch.setenv("SAGE_EMBEDDED_BROWSER_PORT", "43210")
    monkeypatch.setenv("SAGE_EMBEDDED_BROWSER_TOKEN", "tok-123")
    monkeypatch.delenv("SAGE_BROWSER_PATH", raising=False)
    monkeypatch.delenv("SAGE_FIREFOX_PATH", raising=False)

    from backend.tools.browser_launcher import discover_and_select

    cap = discover_and_select()
    assert cap is not None
    assert cap.browser_type == BrowserType.EMBEDDED
    assert cap.cdp_port == 43210
    assert isinstance(cap.launcher, EmbeddedLauncher)
    assert cap.launcher.token == "tok-123"


def test_discover_ignores_incomplete_embedded_env(monkeypatch):
    monkeypatch.setenv("SAGE_EMBEDDED_BROWSER", "1")
    monkeypatch.delenv("SAGE_EMBEDDED_BROWSER_PORT", raising=False)
    monkeypatch.delenv("SAGE_EMBEDDED_BROWSER_TOKEN", raising=False)
    from backend.tools.browser_launcher import _discover_embedded

    assert _discover_embedded() is None


def test_launch_browser_embedded_skips_spawn(monkeypatch):
    cap = SimpleNamespace(
        browser_type=BrowserType.EMBEDDED,
        executable="(embedded)",
        cdp_port=43210,
        cdp_endpoint_strategy="embedded",
        launcher=EmbeddedLauncher(43210, "tok-123"),
    )
    monkeypatch.setattr(browser_cdp, "discover_and_select", lambda: cap)
    manager = browser_cdp.BrowserSessionManager()
    monkeypatch.setattr(browser_cdp, "_manager", manager)

    def _no_spawn(*args, **kwargs):
        raise AssertionError("embedded must not spawn a subprocess")

    monkeypatch.setattr(browser_cdp.subprocess, "Popen", _no_spawn)

    session = browser_cdp.launch_browser(headless=False, browser_id="emb")
    assert session.browser_type == BrowserType.EMBEDDED
    assert session.port == 43210
    assert session.bridge_token == "tok-123"
    assert session.is_alive() is True
    assert manager.get("emb") is session


def test_cdp_command_routes_embedded_to_bridge(monkeypatch):
    calls = []
    monkeypatch.setattr(
        browser_cdp,
        "_embedded_command",
        lambda session, method, params=None, target_id=None: calls.append(
            (session.browser_id, method, params, target_id)
        )
        or {"ok": True},
    )
    result = browser_cdp.cdp_command(_embedded_session(), "Page.navigate", {"url": "x"}, "t1")
    assert result == {"ok": True}
    assert calls == [("emb", "Page.navigate", {"url": "x"}, "t1")]


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_embedded_command_posts_to_bridge(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"result": {"ok": 1}})

    monkeypatch.setattr(browser_cdp.urllib.request, "urlopen", fake_urlopen)
    result = browser_cdp._embedded_command(
        _embedded_session(headless=True), "Runtime.evaluate", {"expression": "1"}, "t1"
    )
    assert result == {"ok": 1}
    assert captured["url"] == "http://127.0.0.1:43210/command"
    assert captured["headers"].get("X-sage-bridge-token") == "tok-123"
    assert captured["body"] == {
        "method": "Runtime.evaluate",
        "params": {"expression": "1"},
        "targetId": "t1",
        "headless": True,
    }


def test_embedded_command_maps_bridge_error(monkeypatch):
    monkeypatch.setattr(
        browser_cdp.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"error": {"message": "boom"}}),
    )
    with pytest.raises(BrowserCDPError, match="boom"):
        browser_cdp._embedded_command(_embedded_session(), "Page.navigate", {})


def test_render_pool_skips_event_channel_for_embedded():
    session = SimpleNamespace(browser_id="emb", browser_type=BrowserType.EMBEDDED)
    assert web_render._ensure_pool_channel(session) is False


def test_browser_health_reports_embedded(monkeypatch):
    import backend.api.diagnostic_routes as routes

    monkeypatch.setattr(
        "backend.tools.browser_cdp.discover_browser_executable", lambda: "(embedded)"
    )
    health = routes.get_browser_health()
    assert health.browserFound is True
    assert health.executable == "Sage 内置浏览器"
    assert health.warning == ""
