# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""受控浏览器跨 frame 真机集成测试。

覆盖 CDP 全帧巡检的关键缝隙（单测全部 stub，测不到真实隔离世界行为）：

- 同源 iframe（KNS 5.5 的 ``#iframeResult`` 结构）；
- 跨源头 iframe（不同端口，``contentDocument`` 不可读，只能走 CDP）；
- frameset ``<frame>``；
- 跨域 frame 内按 ref 点击后，详情页内容能被后续快照读到。

只访问 127.0.0.1 本地 fixture，不触外网；本机无 Chrome/Edge 时整体跳过。
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.domain.tool_policy import ToolPolicy
from backend.services import browser_safety
from backend.tools import browser_cdp, browser_tool
from backend.tools.browser_tool import (
    BrowserInteractTool,
    BrowserNavigateTool,
    BrowserSnapshotTool,
)

pytestmark = [pytest.mark.integration]

RESULT_HTML = """<html><body><h2>检索结果</h2><table>
<tr><td><a href="/detail.html">论文A</a></td><td>作者甲</td></tr>
<tr><td><a href="/detail.html">论文B</a></td><td>作者乙</td></tr>
</table><a id="Page_next" href="/result.html?page=2">下一页</a></body></html>"""

PARENT_HTML = """<html><body><h1>检索</h1>
<iframe id="iframeResult" name="iframeResult" src="/result.html"
        style="width:600px;height:400px"></iframe>
<iframe id="aside" src="__CROSS_BASE__/result.html?aside=1"
        style="width:600px;height:400px"></iframe>
</body></html>"""

FRAMESET_HTML = """<html><frameset cols="50%,50%">
<frame name="left" src="/result.html?left=1">
<frame name="right" src="/result.html?right=1">
</frameset></html>"""

DETAIL_HTML = "<html><body><h1>详情页-论文A</h1></body></html>"
NOT_FOUND_HTML = "<html><body>nf</body></html>"


def _discover_browser() -> None:
    if not browser_cdp.discover_browser_executable():
        pytest.skip("本机未发现 Chrome/Edge —— 跳过跨 frame 真机集成测试")


def _start_fixture(pages):
    class _Handler(BaseHTTPRequestHandler):
        server_version = "CrossFrameFixture"

        def log_message(self, *args):  # noqa: N802 — 静默请求日志
            pass

        def do_GET(self):  # noqa: N802 — http.server 接口
            path = self.path.split("?", 1)[0]
            body = pages.get(path, NOT_FOUND_HTML).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % server.server_address[1]
    return server, base


def _tool(cls, tmp_path):
    return cls(policy=ToolPolicy(workspace_root=str(tmp_path)))


def _element_names(snapshot):
    return [str(item.get("name") or "") for item in snapshot.content.get("elements") or []]


def _wait_for_text(snapshot_tool, browser_id, needle, timeout=6.0):
    deadline = time.monotonic() + timeout
    text = ""
    while time.monotonic() < deadline:
        snapshot = snapshot_tool.execute(mode="full", browser_id=browser_id)
        if snapshot.success:
            text = str(snapshot.content.get("text") or "")
            if needle in text:
                return text
        time.sleep(0.2)
    return text


def test_cross_frame_snapshot_click_and_frameset(tmp_path, monkeypatch):
    _discover_browser()
    # 测试只访问 127.0.0.1 fixture：固定 online 策略，不依赖本机气隙/内网设置。
    monkeypatch.setattr(
        browser_tool,
        "load_network_policy",
        lambda: NetworkPolicy(mode=NetworkMode.ONLINE),
    )
    browser_cdp.get_browser_manager().close_all()

    right_server, right_base = _start_fixture(
        {"/result.html": RESULT_HTML, "/detail.html": DETAIL_HTML}
    )
    left_pages = {
        "/parent.html": PARENT_HTML.replace("__CROSS_BASE__", right_base),
        "/result.html": RESULT_HTML,
        "/frameset.html": FRAMESET_HTML,
        "/detail.html": DETAIL_HTML,
    }
    left_server, left_base = _start_fixture(left_pages)
    session = browser_cdp.launch_browser(headless=True)
    browser_id = session.browser_id
    try:
        browser_safety.grant_site(browser_id, "127.0.0.1", "session")
        navigate = _tool(BrowserNavigateTool, tmp_path)
        snapshot_tool = _tool(BrowserSnapshotTool, tmp_path)
        interact = _tool(BrowserInteractTool, tmp_path)

        result = navigate.execute(url=left_base + "/parent.html", browser_id=browser_id)
        assert result.success is True, result.error

        snapshot = snapshot_tool.execute(browser_id=browser_id)
        assert snapshot.success is True, snapshot.error
        framed = [
            item for item in snapshot.content["elements"] if item.get("frame_url")
        ]
        assert any(
            str(item["frame_url"]).startswith(right_base) for item in framed
        ), framed
        assert any("论文A" in name for name in _element_names(snapshot))

        cross_ref = next(
            item["ref"]
            for item in snapshot.content["elements"]
            if "论文A" in str(item.get("name") or "")
            and str(item.get("frame_url") or "").startswith(right_base)
        )
        click = interact.execute(action="click", ref=cross_ref, browser_id=browser_id)
        assert click.success is True, click.error
        assert "详情页-论文A" in _wait_for_text(snapshot_tool, browser_id, "详情页-论文A")

        result = navigate.execute(url=left_base + "/frameset.html", browser_id=browser_id)
        assert result.success is True, result.error
        frameset_snapshot = snapshot_tool.execute(browser_id=browser_id)
        assert frameset_snapshot.success is True, frameset_snapshot.error
        assert any("论文A" in name for name in _element_names(frameset_snapshot))
        states = [
            frame.get("state") for frame in frameset_snapshot.content.get("frames") or []
        ]
        assert states
        assert all(state == "scanned" for state in states), states
    finally:
        browser_cdp.get_browser_manager().close_all()
        browser_safety.reset_site_policies_for_tests()
        left_server.shutdown()
        left_server.server_close()
        right_server.shutdown()
        right_server.server_close()
