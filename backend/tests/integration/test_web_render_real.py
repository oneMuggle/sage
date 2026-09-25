# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""web_render 真实浏览器渲染链集成测试（R35，总账 §3 P3 第三项）。

补单测 stub 与真实 CDP 行为之间的缝隙：本地 fixture HTTP 服务器 + 真
Chrome/Edge 走完整渲染链（渲染池 → 事件通道 → attach → Network/Page 事件
→ 就绪等待 → 302 重定向 → wait_for → 状态码/完整度标记）。本机未发现
Chrome/Edge 时整体跳过（与 test_browser_tool.test_real_browser_smoke
同口径）。

只访问 127.0.0.1 fixture，不触外网。
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.tools import browser_cdp
from backend.tools.web_render import render_page

pytestmark = [pytest.mark.integration]


def _discover_browser() -> str:
    executable = browser_cdp.discover_browser_executable()
    if not executable:
        pytest.skip("本机未发现 Chrome/Edge —— 跳过真实渲染链集成测试")
    return executable


class _FixtureHandler(BaseHTTPRequestHandler):
    """本地 fixture：/start 302 → /target（含 .item 选择器 + 正文）；/503 直接 503。"""

    server_version = "R35Fixture"

    def log_message(self, *args):  # noqa: N802 — 静默请求日志
        pass

    def do_GET(self):  # noqa: N802 — http.server 接口
        if self.path == "/start":
            self.send_response(302)
            self.send_header("Location", "/target")
            self.end_headers()
        elif self.path == "/target":
            body = (
                "<html><head><title>R35 fixture</title></head><body>"
                '<div class="item">R35 目标内容已渲染</div>'
                "<p>正文文本用于 settle 稳定</p></body></html>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/503":
            body = b"upstream unavailable"
            self.send_response(503)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture(scope="module")
def fixture_server():
    server = HTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture()
def _clean_browser():
    browser_cdp.get_browser_manager().close_all()
    yield
    browser_cdp.get_browser_manager().close_all()


@pytest.mark.usefixtures("_clean_browser")
def test_real_render_chain_follows_redirect_and_marks_wait_for(fixture_server):
    """302 链 → 目标页渲染；wait_for 命中；事件通道在位（R23 接线生效）。"""
    result = render_page(
        f"{fixture_server}/start",
        NetworkPolicy(mode=NetworkMode.ONLINE),
        wait_for=".item",
    )

    assert result["rendered"] is True
    assert result["url"].endswith("/target")
    assert "R35 目标内容已渲染" in result["content"]
    assert result.get("wait_for_satisfied") is True
    assert result.get("rendered_status") == 200
    # R23 接线：渲染池事件通道已建立（ensure_network_tracking 成功）
    assert "browser" not in result  # 无错误字段混入


@pytest.mark.usefixtures("_clean_browser")
def test_real_render_chain_reports_503(fixture_server):
    """503 盾页状态码经渲染链可见（Navigation Timing 兜底或事件，R22/R31）。"""
    result = render_page(f"{fixture_server}/503", NetworkPolicy(mode=NetworkMode.ONLINE))

    # R31：首次 503 触发单次自动重试，第二次仍 503 → 如实返回 + note
    assert result.get("rendered_status") == 503
    assert "render_retried" in (result.get("note") or "")
