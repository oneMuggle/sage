"""浏览器扩展桥核心逻辑测试（无真实浏览器 / 无数据库）。"""

from __future__ import annotations

import asyncio
import hashlib

import pytest

import backend.services.browser_extension_bridge as bridge_module
from backend.services.browser_extension_bridge import (
    BrowserExtensionBridge,
    CommandTimeoutError,
    ExtensionAuthError,
    InMemoryDeviceStore,
    PairingError,
    SharedTabError,
    UnsupportedCommandError,
)
from backend.services.browser_extension_security import is_safe_cookie_domain

pytestmark = pytest.mark.unit

_CNKI_URL = "https://kns.cnki.net/kns8s/defaultresult/index"


class FakeManager:
    """替代真实 BrowserSessionManager（不启动浏览器）。"""

    def __init__(self) -> None:
        self.sessions = {}

    def get(self, browser_id):
        return self.sessions.get(browser_id)

    def register(self, session):
        self.sessions[session.browser_id] = session

    def remove(self, browser_id):
        return self.sessions.pop(browser_id, None)


@pytest.fixture()
def clock():
    return {"now": 1000.0}


@pytest.fixture()
def manager(monkeypatch):
    fake = FakeManager()
    monkeypatch.setattr(bridge_module, "_session_manager", lambda: fake)
    return fake


@pytest.fixture()
def bridge(manager, clock):
    return BrowserExtensionBridge(
        store=InMemoryDeviceStore(), clock=lambda: clock["now"]
    )


def _pair(bridge: BrowserExtensionBridge, label: str = "我的 Chrome"):
    code = bridge.issue_pairing_code()["code"]
    return bridge.pair(code, label)


def _tab(tab_id: int = 7, url: str = _CNKI_URL, title: str = "知网首页"):
    return {"id": tab_id, "url": url, "title": title}


def _share(bridge: BrowserExtensionBridge, device, clock, tab=None):
    bridge._update_shared(device, tab or _tab())
    bridge._devices[device["device_id"]]["last_seen_at"] = clock["now"]


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------


def test_pairing_returns_token_and_persists_only_hash(bridge):
    code = bridge.issue_pairing_code()["code"]
    result = bridge.pair(code, " 我的   Chrome ")

    assert result["device_id"].startswith("dev_")
    assert len(result["device_token"]) > 20
    saved = bridge._store.devices
    assert len(saved) == 1
    assert "device_token" not in saved[0]
    assert saved[0]["token_sha256"] == hashlib.sha256(
        result["device_token"].encode()
    ).hexdigest()
    assert saved[0]["label"] == "我的 Chrome"


def test_pairing_code_is_single_use(bridge):
    code = bridge.issue_pairing_code()["code"]
    bridge.pair(code)
    with pytest.raises(PairingError):
        bridge.pair(code)


def test_pairing_code_expires(bridge, clock):
    code = bridge.issue_pairing_code()["code"]
    clock["now"] += 301
    with pytest.raises(PairingError):
        bridge.pair(code)


def test_five_wrong_codes_lock_pairing_without_destroying_code(bridge, clock):
    code = bridge.issue_pairing_code()["code"]
    for _ in range(5):
        with pytest.raises(PairingError):
            bridge.pair("WRONGCODE1")
    # 锁定窗口内即使输入正确也拒绝，但有效码没有被销毁
    with pytest.raises(PairingError):
        bridge.pair(code)
    clock["now"] += bridge_module.PAIRING_LOCK_SECONDS + 1
    result = bridge.pair(code)
    assert result["device_id"].startswith("dev_")


def test_device_limit(bridge):
    for index in range(5):
        _pair(bridge, f"Chrome {index}")
    with pytest.raises(PairingError):
        _pair(bridge, "Chrome 6")


def test_unknown_token_is_rejected(bridge):
    with pytest.raises(ExtensionAuthError):
        bridge._authenticate("not-a-real-token")


def test_revoke_removes_device(manager, bridge, clock):
    device = _pair(bridge)
    _share(bridge, device, clock)

    assert bridge.revoke_device(device["device_id"]) is True
    assert bridge.list_devices() == []
    assert bridge.shared_summary() is None
    assert manager.get("external") is None
    with pytest.raises(ExtensionAuthError):
        bridge._authenticate(device["device_token"])


# ---------------------------------------------------------------------------
# Shared tab / session registration
# ---------------------------------------------------------------------------


def test_share_registers_external_session(manager, bridge, clock):
    device = _pair(bridge)
    _share(bridge, device, clock)

    session = manager.get("external")
    assert session is not None
    assert session.browser_type.value == "external"
    assert session.external_device_id == device["device_id"]
    assert session.external_tab_id == "7"
    summary = bridge.shared_summary()
    assert summary["host"] == "kns.cnki.net"
    assert summary["origin"] == "https://kns.cnki.net"
    assert summary["title"] == "知网首页"


def test_second_device_cannot_share(manager, bridge, clock):
    first = _pair(bridge, "Chrome A")
    second = _pair(bridge, "Chrome B")
    _share(bridge, first, clock)

    with pytest.raises(SharedTabError):
        bridge._update_shared(second, _tab(tab_id=8))


def test_non_http_tab_is_rejected(bridge):
    device = _pair(bridge)
    with pytest.raises(SharedTabError):
        bridge._update_shared(device, {"id": 1, "url": "file:///etc/passwd"})


async def _wait_for_queue(bridge: BrowserExtensionBridge, device_id: str):
    for _ in range(50):
        queue = bridge._queues.get(device_id)
        if queue is not None:
            return queue
        await asyncio.sleep(0)
    raise AssertionError("command queue was not created")


async def test_detach_fails_pending_commands(manager, bridge, clock):
    device = _pair(bridge)
    _share(bridge, device, clock)

    task = asyncio.create_task(
        bridge._execute_cdp_async("Runtime.evaluate", {"expression": "1"}, None, 2)
    )
    queue = await _wait_for_queue(bridge, device["device_id"])
    await asyncio.wait_for(queue.get(), timeout=1)
    await bridge._detach_async(device["device_id"], reason="user")

    with pytest.raises(SharedTabError):
        await task
    assert manager.get("external") is None
    assert bridge.shared_summary() is None


async def test_poll_with_tab_registers_session_and_returns_command(manager, bridge, clock):
    device = _pair(bridge)
    queue = asyncio.Queue()
    bridge._queues[device["device_id"]] = queue
    queue.put_nowait({"id": "cmd-1", "method": "Runtime.evaluate", "params": {}})

    command = await bridge._poll_async(device, _tab())

    assert command["id"] == "cmd-1"
    session = manager.get("external")
    assert session is not None
    assert session.external_tab_id == "7"
    summary = bridge.shared_summary()
    assert summary["host"] == "kns.cnki.net"

    bridge._update_shared(device, _tab(title="新标题"))
    assert manager.get("external") is session
    assert bridge.shared_summary()["title"] == "新标题"


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------


async def test_execute_cdp_round_trip(bridge, clock):
    device = _pair(bridge)
    _share(bridge, device, clock)

    task = asyncio.create_task(
        bridge._execute_cdp_async(
            "Runtime.evaluate", {"expression": "1+1", "returnByValue": True}, None, 2
        )
    )
    command = await asyncio.wait_for(
        (await _wait_for_queue(bridge, device["device_id"])).get(), timeout=1
    )
    assert command["method"] == "Runtime.evaluate"
    assert command["params"]["expression"] == "1+1"

    resolved = await bridge._resolve_async(
        device["device_id"], command["id"], True, {"result": {"value": 2}}, None
    )
    assert resolved is True
    assert await task == {"result": {"value": 2}}


async def test_execute_cdp_requires_share(bridge):
    _pair(bridge)
    with pytest.raises(SharedTabError):
        await bridge._execute_cdp_async("Runtime.evaluate", {}, None, 1)


async def test_execute_cdp_rejects_other_target(bridge, clock):
    device = _pair(bridge)
    _share(bridge, device, clock)
    with pytest.raises(SharedTabError):
        await bridge._execute_cdp_async("Runtime.evaluate", {}, "999", 1)


async def test_network_get_cookies_is_scoped_to_shared_url(bridge, clock):
    device = _pair(bridge)
    _share(bridge, device, clock)
    task = asyncio.create_task(
        bridge._execute_cdp_async(
            "Network.getCookies", {"urls": ["https://evil.example/"]}, None, 2
        )
    )
    command = await asyncio.wait_for(
        (await _wait_for_queue(bridge, device["device_id"])).get(), timeout=1
    )
    assert command["params"] == {"urls": [_CNKI_URL]}
    await bridge._resolve_async(device["device_id"], command["id"], True, {}, None)
    await task


async def test_blocked_methods_are_explicit(bridge, clock):
    device = _pair(bridge)
    _share(bridge, device, clock)
    with pytest.raises(UnsupportedCommandError):
        await bridge._execute_cdp_async("Target.createTarget", {"url": "about:blank"}, None, 1)
    with pytest.raises(UnsupportedCommandError):
        await bridge._execute_cdp_async("Browser.close", {}, None, 1)
    with pytest.raises(UnsupportedCommandError):
        await bridge._execute_cdp_async("Network.getAllCookies", {}, None, 1)
    with pytest.raises(UnsupportedCommandError):
        await bridge._execute_cdp_async("Emulation.setDeviceMetricsOverride", {}, None, 1)


async def test_command_timeout(bridge, clock):
    device = _pair(bridge)
    _share(bridge, device, clock)
    with pytest.raises(CommandTimeoutError):
        await bridge._execute_cdp_async("Runtime.evaluate", {}, None, 0.05)


async def test_offline_device_is_rejected(bridge, clock):
    device = _pair(bridge)
    _share(bridge, device, clock)
    clock["now"] += bridge_module.OFFLINE_AFTER_SECONDS + 1
    with pytest.raises(SharedTabError):
        await bridge._execute_cdp_async("Runtime.evaluate", {}, None, 1)


# ---------------------------------------------------------------------------
# Session snapshot
# ---------------------------------------------------------------------------


def test_sync_session_filters_domains_and_origins(bridge, clock, monkeypatch):
    calls = {"credential": [], "storage": []}

    def fake_save_credential(domain, cookies, source_profile="", repo=None):
        calls["credential"].append((domain, len(cookies), source_profile))

    def fake_save_storage_state(domain, cookies, origins, source_profile="", repo=None):
        calls["storage"].append((domain, len(cookies), origins, source_profile))

    from backend.tools import credential_vault

    monkeypatch.setattr(credential_vault, "save_credential", fake_save_credential)
    monkeypatch.setattr(credential_vault, "save_storage_state", fake_save_storage_state)

    device = _pair(bridge)
    _share(bridge, device, clock)

    result = bridge.sync_session(
        device["device_token"],
        {
            "url": _CNKI_URL,
            "cookies": [
                {"name": "SID", "value": "secret", "domain": ".cnki.net"},
                {"name": "evil", "value": "x", "domain": ".example.com"},
                {"name": "public", "value": "x", "domain": "net"},
            ],
            "origins": [
                {"origin": "https://kns.cnki.net", "localStorage": {"vtoken": "abc"}},
                {"origin": "https://evil.example", "localStorage": {"x": "y"}},
            ],
        },
    )

    assert result["total_cookies"] == 1
    assert result["has_storage"] is True
    assert calls["storage"]
    domain, count, origins, profile = calls["storage"][0]
    assert domain == ".cnki.net"
    assert count == 1
    assert origins == [
        {"origin": "https://kns.cnki.net", "localStorage": {"vtoken": "abc"}}
    ]
    assert profile == "browser-extension"
    assert "secret" not in str(result)
    assert "abc" not in str(result)


def test_sync_session_requires_matching_shared_tab(bridge, clock):
    device = _pair(bridge)
    _share(bridge, device, clock)
    with pytest.raises(SharedTabError):
        bridge.sync_session(
            device["device_token"],
            {"url": "https://example.com", "cookies": [{"name": "a", "domain": ".example.com"}]},
        )


def test_sync_session_rejects_localstorage_only(bridge, clock):
    device = _pair(bridge)
    _share(bridge, device, clock)
    with pytest.raises(SharedTabError, match="Cookie"):
        bridge.sync_session(
            device["device_token"],
            {
                "url": _CNKI_URL,
                "cookies": [],
                "origins": [
                    {"origin": "https://kns.cnki.net", "localStorage": {"vtoken": "abc"}}
                ],
            },
        )


def test_sync_session_does_not_overwrite_header_credentials(bridge, clock, monkeypatch):
    from backend.tools import credential_vault

    monkeypatch.setattr(
        credential_vault,
        "list_credentials",
        lambda: [{"domain": ".cnki.net", "kind": "header"}],
    )
    monkeypatch.setattr(
        credential_vault,
        "save_credential",
        lambda *args, **kwargs: pytest.fail("header credential was overwritten"),
    )
    monkeypatch.setattr(
        credential_vault,
        "save_storage_state",
        lambda *args, **kwargs: pytest.fail("header credential was overwritten"),
    )
    device = _pair(bridge)
    _share(bridge, device, clock)
    with pytest.raises(SharedTabError, match="header"):
        bridge.sync_session(
            device["device_token"],
            {
                "url": _CNKI_URL,
                "cookies": [{"name": "SID", "value": "x", "domain": ".cnki.net"}],
            },
        )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def test_list_devices_masks_token_and_reports_connection(bridge, clock):
    device = _pair(bridge)
    _share(bridge, device, clock)

    [entry] = bridge.list_devices()
    assert entry["device_id"] == device["device_id"]
    assert entry["connected"] is True
    assert entry["sharing"] is True
    assert "token" not in str(entry)
    assert device["device_token"] not in str(entry)

    clock["now"] += bridge_module.OFFLINE_AFTER_SECONDS + 1
    [stale] = bridge.list_devices()
    assert stale["connected"] is False


def test_cookie_domain_rejects_public_suffix_and_ip_suffix_games():
    assert is_safe_cookie_domain("kns.cnki.net", ".cnki.net") is True
    assert is_safe_cookie_domain("kns.cnki.net", "kns.cnki.net") is True
    assert is_safe_cookie_domain("kns.cnki.net", "net") is False
    assert is_safe_cookie_domain("foo.co.uk", "co.uk") is False
    assert is_safe_cookie_domain("127.0.0.1", "127.0.0.1") is True
    assert is_safe_cookie_domain("127.0.0.1", "0.0.1") is False
