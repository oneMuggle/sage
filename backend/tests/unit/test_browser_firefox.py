"""Firefox 多浏览器支持（main 分支侧移植，对齐 release/win7）。

覆盖：固定端口 CDP 握手（``/json/version``）、launch_browser 接入
（会话类型 / 端口 / WS 路径）与握手失败清理。Firefox 兜底服务于
Win7 等无法安装新 Chrome 的环境（见 docs/technical/160）。
"""

from __future__ import annotations

import json
import time

import pytest

import backend.tools.browser_cdp as cdp
from backend.tools.browser_cdp import BrowserCDPError, BrowserType

pytestmark = pytest.mark.unit


class _FakeProcess:
    pid = 4321

    def __init__(self, returncode=None):
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def terminate(self):
        pass

    def kill(self):
        pass

    def wait(self, timeout=None):
        return self.returncode or 0


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def getcode(self):
        return 200

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _raise(exc):
    def _inner(*args, **kwargs):
        raise exc

    return _inner


def test_wait_for_firefox_cdp_parses_ws_path_with_query(monkeypatch):
    monkeypatch.setattr(
        cdp.urllib.request,
        "urlopen",
        lambda request, timeout: _FakeResponse(
            {
                "webSocketDebuggerUrl": (
                    "ws://127.0.0.1:9229/devtools/browser/abc-123?ws=1"
                )
            }
        ),
    )

    port, ws_path = cdp._wait_for_firefox_cdp(_FakeProcess(), time.monotonic() + 5)

    assert port == cdp.FIREFOX_CDP_PORT == 9229
    assert ws_path == "/devtools/browser/abc-123?ws=1"


def test_wait_for_firefox_cdp_retries_until_debug_server_ready(monkeypatch):
    monkeypatch.setattr(cdp, "_FIREFOX_POLL_INTERVAL", 0.01)
    attempts = {"count": 0}

    def _urlopen(request, timeout):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise cdp.urllib.error.URLError("connection refused")
        return _FakeResponse(
            {"webSocketDebuggerUrl": "ws://127.0.0.1:9229/devtools/browser/x"}
        )

    monkeypatch.setattr(cdp.urllib.request, "urlopen", _urlopen)

    port, ws_path = cdp._wait_for_firefox_cdp(_FakeProcess(), time.monotonic() + 5)

    assert (port, ws_path) == (9229, "/devtools/browser/x")
    assert attempts["count"] == 3


def test_wait_for_firefox_cdp_raises_when_process_exits(monkeypatch):
    monkeypatch.setattr(
        cdp.urllib.request,
        "urlopen",
        _raise(AssertionError("进程已退出时不应继续探测")),
    )

    with pytest.raises(BrowserCDPError, match="提前退出"):
        cdp._wait_for_firefox_cdp(_FakeProcess(returncode=1), time.monotonic() + 5)


def test_wait_for_firefox_cdp_times_out(monkeypatch):
    monkeypatch.setattr(cdp, "_FIREFOX_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(
        cdp.urllib.request,
        "urlopen",
        _raise(cdp.urllib.error.URLError("connection refused")),
    )

    with pytest.raises(BrowserCDPError, match="超时"):
        cdp._wait_for_firefox_cdp(_FakeProcess(), time.monotonic() + 0.05)


def _prepare_launch(monkeypatch, tmp_path, handshake):
    """公共前置：隔离环境/设置/进程，返回 (manager, captured, profile_dir)。

    release/win7 的启动链走 ``browser_launcher.discover_and_select`` +
    ``FirefoxLauncher.build_command/wait_for_cdp``（main 为 browser_cdp 内联
    实现），因此这里桩的是 launcher 能力对象而非 ``discover_browser_executable``。
    """
    from backend.tools import http_factory
    from backend.tools.browser_launcher import (
        BrowserCapability,
        BrowserType as LauncherBrowserType,
        FirefoxLauncher,
    )

    exe = tmp_path / "firefox"
    exe.write_text("")
    profile_dir = tmp_path / "profile"
    manager = cdp.BrowserSessionManager()
    captured = {"commands": []}

    def _popen(command, **kwargs):
        captured["commands"].append(command)
        return _FakeProcess()

    launcher = FirefoxLauncher()
    monkeypatch.setattr(launcher, "wait_for_cdp", handshake)
    capability = BrowserCapability(
        browser_type=LauncherBrowserType.FIREFOX,
        executable=str(exe),
        version=None,
        cdp_port=cdp.FIREFOX_CDP_PORT,
        cdp_endpoint_strategy="http_json_version",
        launcher=launcher,
    )

    monkeypatch.setattr(cdp, "_manager", manager)
    monkeypatch.setattr(cdp, "_ephemeral_root", lambda: tmp_path)
    monkeypatch.setattr(cdp, "discover_and_select", lambda user_path=None: capability)
    monkeypatch.setattr(
        cdp.tempfile, "mkdtemp", lambda prefix=None, dir=None: str(profile_dir)
    )
    monkeypatch.setattr(cdp.subprocess, "Popen", _popen)
    monkeypatch.setattr(http_factory, "browser_proxy_flag", lambda: "")
    return manager, captured, profile_dir


def test_launch_browser_firefox_registers_session(monkeypatch, tmp_path):
    manager, captured, _ = _prepare_launch(
        monkeypatch,
        tmp_path,
        lambda process, user_data_dir, timeout=None: (
            cdp.FIREFOX_CDP_PORT,
            "/devtools/browser/abc-123?ws=1",
        ),
    )

    session = cdp.launch_browser(headless=True, browser_id="ff-1")

    assert session.browser_type == BrowserType.FIREFOX
    assert session.port == 9229
    assert session.ws_path == "/devtools/browser/abc-123?ws=1"
    assert captured["commands"][0][1] == "-headless"
    assert manager.get("ff-1") is session


def test_launch_browser_firefox_handshake_failure_cleans_up(monkeypatch, tmp_path):
    manager, _, profile_dir = _prepare_launch(
        monkeypatch,
        tmp_path,
        _raise(BrowserCDPError("握手失败")),
    )
    terminated = {}
    monkeypatch.setattr(
        cdp,
        "_terminate_session",
        lambda session: terminated.setdefault("session", session),
    )

    with pytest.raises(BrowserCDPError, match="握手失败"):
        cdp.launch_browser(headless=True, browser_id="ff-fail")

    assert terminated["session"].user_data_dir == str(profile_dir)
    assert terminated["session"].browser_type == BrowserType.FIREFOX
    assert manager.count() == 0
