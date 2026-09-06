"""浏览器自动化工具单元测试（G7）。

CDP 交互全部 stub（monkeypatch cdp_command / launch_browser），只测工具
逻辑：URL scheme 门禁、JS 构造器转义、参数校验、会话管理器生命周期、
截图落盘、错误映射。真浏览器 smoke 用 skipif 门控（CI/本机无浏览器时
跳过）。

WS 帧层（browser_ws）用真实 socket 对拍：本地起一个按 RFC 应答的
迷你服务端线程，覆盖握手/掩码/分片/Ping/Close。
"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.domain.tool_policy import ToolPolicy
from backend.tools import browser_cdp, browser_tool, web_render
from backend.tools.browser_cdp import BrowserSession, BrowserSessionManager
from backend.tools.browser_tool import (
    BrowserCloseTool,
    BrowserInteractTool,
    BrowserLaunchTool,
    BrowserNavigateTool,
    BrowserScreenshotTool,
    BrowserSnapshotTool,
    _js_click,
    _js_type,
    validate_url,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# browser_ws 帧层：本地迷你 WS 服务端对拍
# ---------------------------------------------------------------------------


class _MiniWSServer:
    """按 RFC 6455 应答的极简服务端：收文本回声，Ping→Pong，可发分片。"""

    def __init__(self) -> None:
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self.port = self._listener.getsockname()[1]
        self._thread: Optional[threading.Thread] = None

    def __enter__(self):
        ready = threading.Event()
        self._thread = threading.Thread(target=self._serve, args=(ready,), daemon=True)
        self._thread.start()
        ready.wait(timeout=5)
        return self

    def __exit__(self, *exc):
        self._listener.close()
        if self._thread:
            self._thread.join(timeout=2)

    def _recv_exact(self, sock: socket.socket, count: int) -> bytes:
        data = b""
        while len(data) < count:
            chunk = sock.recv(count - len(data))
            if not chunk:
                raise OSError("closed")
            data += chunk
        return data

    def _serve(self, ready: threading.Event) -> None:
        ready.set()
        sock, _ = self._listener.accept()
        try:
            handshake = b""
            while b"\r\n\r\n" not in handshake:
                handshake += sock.recv(4096)
            header = handshake.decode("latin-1")
            key = next(
                line.split(":", 1)[1].strip()
                for line in header.split("\r\n")
                if line.lower().startswith("sec-websocket-key")
            )
            accept = base64.b64encode(
                hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
            ).decode()
            sock.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode("ascii")
            )
            # 回环：收一帧回一帧（Ping→Pong 由客户端处理；这里只回显文本）
            while True:
                first, second = self._recv_exact(sock, 2)
                opcode = first & 0x0F
                masked = bool(second & 0x80)
                length = second & 0x7F
                if length == 126:
                    (length,) = struct.unpack("!H", self._recv_exact(sock, 2))
                elif length == 127:
                    (length,) = struct.unpack("!Q", self._recv_exact(sock, 8))
                mask = self._recv_exact(sock, 4) if masked else b""
                payload = self._recv_exact(sock, length) if length else b""
                if masked and payload:
                    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
                if opcode == 0x8:
                    break
                if opcode == 0x1:
                    # 服务端帧不掩码：FIN 文本回显
                    out = struct.pack("!BB", 0x81, len(payload)) + payload
                    sock.sendall(out)
        except OSError:
            pass
        finally:
            sock.close()


def test_ws_roundtrip_echo_and_ping():
    from backend.tools.browser_ws import ws_close, ws_connect, ws_recv_text, ws_send_text

    with _MiniWSServer() as server:
        sock = ws_connect("127.0.0.1", server.port, "/devtools/browser/test")
        ws_send_text(sock, json.dumps({"id": 1, "method": "ping"}))
        assert json.loads(ws_recv_text(sock))["id"] == 1
        ws_send_text(sock, "hello 帧")  # 非 ASCII payload
        assert ws_recv_text(sock) == "hello 帧"
        ws_close(sock)


def test_ws_rejects_non_loopback():
    from backend.tools.browser_ws import ws_connect

    with pytest.raises(Exception, match="非回环"):
        ws_connect("example.com", 1234, "/")


# ---------------------------------------------------------------------------
# URL scheme 门禁
# ---------------------------------------------------------------------------


def test_validate_url_allows_http_https_about_data():
    assert validate_url("https://example.com") is None
    assert validate_url("http://127.0.0.1:8000/x") is None
    assert validate_url("about:blank") is None
    assert validate_url("data:text/html,<b>hi</b>") is None


def test_validate_url_blocks_local_and_injection_schemes():
    for url in ("file:///etc/passwd", "chrome://settings", "javascript:alert(1)", "ftp://x"):
        assert validate_url(url) is not None


# ---------------------------------------------------------------------------
# JS 构造器转义
# ---------------------------------------------------------------------------


def test_js_click_escapes_selector_and_text():
    js = _js_click(selector="a[title='it\\'s']")
    assert "querySelector" in js
    js_by_text = _js_click(text='点我 "here"')
    # json.dumps 默认 ensure_ascii —— 中文以 \uXXXX 进 JS 字面量（语义等价）
    assert "\\u70b9\\u6211" in js_by_text
    assert "here" in js_by_text


def test_js_type_uses_native_setter_and_events():
    js = _js_type("#user", "va'lue\nline", clear=True)
    assert "HTMLInputElement" in js
    assert "'input'" in js
    assert "'change'" in js
    assert "va'lue\\nline" in js  # json.dumps 转义注入


# ---------------------------------------------------------------------------
# 会话管理器
# ---------------------------------------------------------------------------


def _fake_session(browser_id: str, alive: bool = True) -> BrowserSession:
    process = SimpleNamespace(poll=lambda: None if alive else 1, terminate=lambda: None, kill=lambda: None, wait=lambda timeout=None: None)
    return BrowserSession(
        browser_id=browser_id,
        executable="fake-browser",
        headless=True,
        user_data_dir="/tmp/unused",
        process=process,
        port=1,
        ws_path="/devtools/browser/x",
    )


def test_manager_require_and_dead_session_eviction():
    manager = BrowserSessionManager()
    manager.register(_fake_session("b1", alive=True))
    assert manager.get(None).browser_id == "b1"  # 唯一实例免传 id

    manager.register(_fake_session("b2", alive=True))
    assert manager.get(None) is None  # 多实例必须指名
    assert manager.get("b2").browser_id == "b2"

    dead = _fake_session("b3", alive=False)
    manager.register(dead)
    with pytest.raises(browser_cdp.BrowserCDPError, match="已退出"):
        manager.require("b3")
    assert manager.get("b3") is None  # 死实例被移除

    manager.close_all()
    assert manager.count() == 0


def test_manager_cap():
    manager = BrowserSessionManager()
    for index in range(browser_cdp.MAX_BROWSER_SESSIONS):
        manager.register(_fake_session(f"b{index}"))
    with pytest.raises(browser_cdp.BrowserCDPError, match="上限"):
        manager.register(_fake_session("overflow"))


# ---------------------------------------------------------------------------
# 工具逻辑（CDP stub）
# ---------------------------------------------------------------------------


@pytest.fixture()
def stubbed(monkeypatch):
    """固定一个活会话 + 可编程的 cdp_command 假体。

    W2 起 navigate 的就绪/稳定等待统一走 web_render.wait_page_ready，
    它引用 web_render.cdp_command / web_render.time —— 一并对齐同一假体
    与假时钟（就绪等待零真实耗时）。
    """
    session = _fake_session("b1")
    manager = BrowserSessionManager()
    manager.register(session)
    monkeypatch.setattr(browser_cdp, "_manager", manager)
    calls: List[Dict[str, Any]] = []

    def _fake_cdp(session_, method, params=None, target_id=None):
        calls.append({"method": method, "params": params or {}, "target": target_id})
        return _fake_cdp.results.pop(0)

    _fake_cdp.results = []  # type: ignore[attr-defined]
    monkeypatch.setattr(browser_tool, "cdp_command", _fake_cdp)
    monkeypatch.setattr(web_render, "cdp_command", _fake_cdp)

    class _FakeClock:
        def __init__(self) -> None:
            self.now = 0.0

        def monotonic(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.now += seconds

    monkeypatch.setattr(web_render, "time", _FakeClock())
    return SimpleNamespace(session=session, calls=calls, results=_fake_cdp.results)


def _tool(cls):
    return cls(policy=ToolPolicy(workspace_root="."))


def test_navigate_happy_path_with_settle(stubbed, monkeypatch):
    stubbed.results.extend(
        [
            {},  # Page.navigate
            {"result": {"value": "complete"}},  # readyState poll
            {"result": {"value": 0}},  # settle: innerText 长度（SPA hydrate 窗口）
            {"result": {"value": 0}},
            {"result": {"value": 0}},  # 连续 2 轮不变 → 稳定，提前返回
            {"result": {"value": json.dumps({"url": "https://x/", "title": "X"})}},
        ]
    )
    result = _tool(BrowserNavigateTool).execute(url="https://x/", browser_id="b1")
    assert result.success is True
    assert result.content["title"] == "X"
    assert stubbed.calls[0]["method"] == "Page.navigate"


def test_navigate_offline_gate_blocks_http_only(stubbed, monkeypatch):
    """W4：http/https 受网络模式门禁；about: 等无网络 scheme 不误伤。"""
    monkeypatch.setattr(
        browser_tool,
        "load_network_policy",
        lambda: NetworkPolicy(mode=NetworkMode.OFFLINE),
    )
    result = _tool(BrowserNavigateTool).execute(url="https://x/", browser_id="b1")
    assert result.success is False
    assert "network_mode_offline" in result.error

    monkeypatch.setattr(
        browser_tool,
        "load_network_policy",
        lambda: NetworkPolicy(
            mode=NetworkMode.INTRANET, allowed_hosts=("*.example.internal",)
        ),
    )
    result = _tool(BrowserNavigateTool).execute(url="https://evil.example/", browser_id="b1")
    assert result.success is False
    assert "host_not_allowed" in result.error

    # about:blank 无网络访问 —— 过门禁，走到导航层（stub 下成功）
    stubbed.results.extend(
        [
            {},  # Page.navigate
            {"result": {"value": "complete"}},
            {"result": {"value": 0}},
            {"result": {"value": 0}},
            {"result": {"value": 0}},
            {"result": {"value": json.dumps({"url": "about:blank", "title": ""})}},
        ]
    )
    result = _tool(BrowserNavigateTool).execute(url="about:blank", browser_id="b1")
    assert result.success is True


def test_wait_page_settled_delegates_to_web_render(stubbed, monkeypatch):
    """W2：就绪/稳定等待逻辑收口在 web_render，browser_tool 只留委派壳。"""
    seen = []
    monkeypatch.setattr(
        browser_tool, "wait_page_ready", lambda session, target: seen.append((session, target))
    )
    browser_tool._wait_page_settled(stubbed.session, "t1")
    assert seen == [(stubbed.session, "t1")]


def test_navigate_rejects_bad_scheme_and_reports_error_text(stubbed):
    assert _tool(BrowserNavigateTool).execute(url="file:///etc/passwd").success is False
    assert "file" in _tool(BrowserNavigateTool).execute(url="file:///x").error

    stubbed.results.extend([{"errorText": "ERR_NAME_NOT_RESOLVED"}])
    result = _tool(BrowserNavigateTool).execute(url="https://nope.example", browser_id="b1")
    assert result.success is False
    assert "ERR_NAME_NOT_RESOLVED" in result.error


def test_snapshot_caps_text(stubbed, monkeypatch):
    monkeypatch.setattr(browser_tool, "SNAPSHOT_TEXT_CAP", 8)
    stubbed.results.append({"result": {"value": json.dumps({"url": "u", "title": "t", "text": "x"})}})
    result = _tool(BrowserSnapshotTool).execute(browser_id="b1")
    assert result.success is True
    # 截断发生在页面侧（JS slice）—— 锁定表达式包含上限
    expression = stubbed.calls[0]["params"]["expression"]
    assert "slice(0,8)" in expression.replace(" ", "")


def test_interact_maps_not_found_to_failure(stubbed):
    stubbed.results.append({"result": {"value": {"ok": False, "info": "not-found"}}})
    result = _tool(BrowserInteractTool).execute(action="click", text="登录", browser_id="b1")
    assert result.success is False
    assert "browser_snapshot" in result.error


def test_interact_validation(stubbed):
    tool = _tool(BrowserInteractTool)
    assert tool.execute(action="dance").success is False
    assert tool.execute(action="click").success is False  # 无 selector/text
    assert tool.execute(action="type").success is False  # 无 selector
    assert tool.execute(action="type", selector="#a", value=None).success is False
    assert tool.execute(action="press").success is False  # 无 key
    assert tool.execute(action="scroll", value="abc").success is False
    assert tool.execute(action="click", text="x", bogus=1).success is False


def test_interact_happy_paths(stubbed):
    tool = _tool(BrowserInteractTool)
    stubbed.results.append({"result": {"value": {"ok": True, "info": "BUTTON 登录"}}})
    assert tool.execute(action="click", text="登录", browser_id="b1").success is True
    stubbed.results.append({"result": {"value": {"ok": True, "info": "typed 5 chars"}}})
    assert (
        tool.execute(action="type", selector="#q", value="hello", browser_id="b1").success
        is True
    )
    stubbed.results.append({"result": {"value": {"ok": True, "info": "scrolled to y=800"}}})
    assert tool.execute(action="scroll", value=800, browser_id="b1").success is True


def test_screenshot_writes_workspace_file(stubbed, tmp_path):
    png = base64.b64encode(b"\x89PNG fake").decode()
    stubbed.results.append({"data": png})  # cdp_command 返回 payload（无 result 包裹）
    tool = BrowserScreenshotTool(policy=ToolPolicy(workspace_root=str(tmp_path)))
    result = tool.execute(browser_id="b1", path="shots/one.png")
    assert result.success is True
    assert result.content["bytes"] == 9
    assert (tmp_path / "shots" / "one.png").read_bytes() == b"\x89PNG fake"


def test_screenshot_requires_workspace(stubbed):
    result = BrowserScreenshotTool(policy=ToolPolicy()).execute(browser_id="b1")
    assert result.success is False
    assert "绑定工作区" in result.error


def test_screenshot_rejects_path_outside_workspace(stubbed, tmp_path):
    tool = BrowserScreenshotTool(policy=ToolPolicy(workspace_root=str(tmp_path)))
    result = tool.execute(browser_id="b1", path="../escape.png")
    assert result.success is False
    assert "path_outside_workspace" in result.error


def test_close_target_vs_browser(stubbed, monkeypatch):
    tool = _tool(BrowserCloseTool)
    stubbed.results.append({})
    result = tool.execute(browser_id="b1", target_id="t9")
    assert result.success is True
    assert result.content["closed"] == "target"

    removed = {}
    monkeypatch.setattr(
        browser_cdp, "_terminate_session", lambda s: removed.update({s.browser_id: True})
    )
    result = tool.execute(browser_id="b1")
    assert result.success is True
    assert result.content["closed"] == "browser"
    assert removed.get("b1") is True


def test_unknown_browser_id_maps_to_error():
    browser_cdp.get_browser_manager().close_all()
    result = _tool(BrowserSnapshotTool).execute(browser_id="ghost")
    assert result.success is False
    assert "未知 browser_id" in result.error


def test_launch_tool_reports_discovery_failure(monkeypatch):
    monkeypatch.setattr(browser_cdp, "discover_browser_executable", lambda: None)
    result = _tool(BrowserLaunchTool).execute()
    assert result.success is False
    assert "SAGE_BROWSER_PATH" in result.error


# ---------------------------------------------------------------------------
# 真浏览器 smoke（有 Chrome/Edge 才跑；无则跳过）
# ---------------------------------------------------------------------------


def test_real_browser_smoke():
    executable = browser_cdp.discover_browser_executable()
    if not executable:
        pytest.skip("本机未发现 Chrome/Edge —— 跳过真浏览器 smoke")
    browser_cdp.get_browser_manager().close_all()
    session = browser_cdp.launch_browser(headless=True)
    try:
        result = _tool(BrowserNavigateTool).execute(url="about:blank", browser_id=session.browser_id)
        assert result.success is True
        result = _tool(BrowserSnapshotTool).execute(browser_id=session.browser_id)
        assert result.success is True
        assert result.content["url"].startswith("about:blank")
    finally:
        browser_cdp.get_browser_manager().close_all()
