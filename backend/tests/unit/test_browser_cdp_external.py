"""BrowserType.EXTERNAL 与现有 CDP 工具层的接入测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import backend.tools.browser_cdp as cdp
from backend.services import browser_extension_bridge as bridge_module
from backend.services.browser_extension_bridge import SharedTabError
from backend.tools import browser_tool

pytestmark = pytest.mark.unit


class FakeProcess:
    pid = 0

    def poll(self):
        return None

    def terminate(self):
        return None

    def kill(self):
        return None

    def wait(self, timeout=None):
        return 0


def _session(**overrides):
    values = {
        "browser_id": "external",
        "executable": "(browser-extension)",
        "headless": False,
        "user_data_dir": "",
        "process": FakeProcess(),
        "port": 0,
        "ws_path": "",
        "persistent": True,
        "profile_name": "browser-extension",
        "browser_type": cdp.BrowserType.EXTERNAL,
        "external_device_id": "dev_x",
        "external_tab_id": "7",
    }
    values.update(overrides)
    return cdp.BrowserSession(**values)


def test_cdp_command_dispatches_to_extension(monkeypatch):
    calls = []

    def fake_execute(method, params, target_id):
        calls.append((method, params, target_id))
        return {"result": {"value": 42}}

    monkeypatch.setattr(
        bridge_module.browser_extension_bridge, "execute_cdp", fake_execute
    )
    result = cdp.cdp_command(
        _session(), "Runtime.evaluate", {"expression": "6*7"}, target_id="7"
    )
    assert result == {"result": {"value": 42}}
    assert calls == [("Runtime.evaluate", {"expression": "6*7"}, "7")]


def test_extension_errors_become_browser_cdp_errors(monkeypatch):
    def fake_execute(method, params, target_id):
        raise SharedTabError("浏览器扩展未共享标签页")

    monkeypatch.setattr(
        bridge_module.browser_extension_bridge, "execute_cdp", fake_execute
    )
    with pytest.raises(cdp.BrowserCDPError, match="浏览器扩展桥"):
        cdp.cdp_command(_session(), "Runtime.evaluate", {})


def test_page_targets_come_from_shared_tab(monkeypatch):
    def fake_execute(method, params, target_id):
        assert method == "Target.getTargets"
        return {
            "targetInfos": [
                {"targetId": "7", "type": "page", "url": "https://kns.cnki.net/"},
                {"targetId": "service", "type": "service_worker", "url": "https://x/"},
            ]
        }

    monkeypatch.setattr(
        bridge_module.browser_extension_bridge, "execute_cdp", fake_execute
    )
    targets = cdp._list_page_targets(_session())
    assert [item["targetId"] for item in targets] == ["7"]
    assert cdp.ensure_page_target(_session()) == "7"


def test_external_without_pages_does_not_create_targets(monkeypatch):
    monkeypatch.setattr(
        bridge_module.browser_extension_bridge,
        "execute_cdp",
        lambda method, params, target_id: {"targetInfos": []},
    )
    with pytest.raises(cdp.BrowserCDPError, match="标签页不可用"):
        cdp.ensure_page_target(_session())


def test_terminate_external_is_a_noop(monkeypatch):
    called = {"getTargets": 0}

    def fake_execute(method, params, target_id):
        called["getTargets"] += 1
        return {"targetInfos": []}

    monkeypatch.setattr(
        bridge_module.browser_extension_bridge, "execute_cdp", fake_execute
    )
    cdp._terminate_session(_session())
    assert called["getTargets"] == 0


def test_unique_session_resolution_prefers_shared_tab():
    manager = cdp.BrowserSessionManager()
    chrome = _session(browser_id="chrome-1", browser_type=cdp.BrowserType.CHROME)
    external = _session()
    manager.register(chrome)
    manager.register(external)

    assert manager.get(None) is external
    assert manager.get("chrome-1") is chrome


def test_external_session_is_exempt_from_session_cap():
    manager = cdp.BrowserSessionManager()
    for index in range(cdp.MAX_BROWSER_SESSIONS):
        manager.register(
            _session(browser_id=f"chrome-{index}", browser_type=cdp.BrowserType.CHROME)
        )
    external = _session()
    manager.register(external)
    assert manager.get("external") is external


def test_close_tool_refuses_to_close_user_shared_tab(monkeypatch):
    session = _session()
    manager = SimpleNamespace(remove=lambda _browser_id: pytest.fail("removed"))
    monkeypatch.setattr(browser_tool, "get_browser_manager", lambda: manager)
    monkeypatch.setattr(browser_tool, "_resolve_session", lambda _browser_id: session)

    result = browser_tool.BrowserCloseTool().execute()

    assert result.success is False
    assert "共享标签页" in (result.error or "")


def test_extension_id_constant_matches_bridge():
    assert cdp.EXTENSION_BROWSER_ID == bridge_module.EXTENSION_BROWSER_ID


def test_external_session_accepts_embedded_style_annotations():
    """会话记录可携带外部设备 / 标签页注解而不影响其它类型。"""
    session = _session(external_device_id="dev_abc", external_tab_id="9")
    assert isinstance(session, cdp.BrowserSession)
    assert session.external_device_id == "dev_abc"
    assert session.browser_type == cdp.BrowserType.EXTERNAL
