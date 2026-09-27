"""R153 — MCP OAuth loopback 回调服务单元测试。

覆盖：随机端口启动、redirect_uri 形状、/callback 捕获完整 URL（含
query）、非 callback 路径 404、wait 成功与短超时、close 停服、
context manager 自动关闭。全部走 127.0.0.1 回环，无外发流量。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.mcp.oauth_loopback import LoopbackCallbackServer

pytestmark = pytest.mark.unit


def test_server_starts_on_random_loopback_port():
    with LoopbackCallbackServer() as server:
        assert server.port > 0
        assert server.redirect_uri == f"http://127.0.0.1:{server.port}/callback"
        assert server.captured is None


def test_get_callback_captures_full_url():
    server = LoopbackCallbackServer()
    try:
        resp = httpx.get(
            f"http://127.0.0.1:{server.port}/callback?code=xyz&state=s1", timeout=5
        )
        assert resp.status_code == 200
        assert "授权完成" in resp.text
        assert server.captured == f"http://127.0.0.1:{server.port}/callback?code=xyz&state=s1"
    finally:
        server.close()


def test_non_callback_path_returns_404_and_keeps_captured_none():
    server = LoopbackCallbackServer()
    try:
        resp = httpx.get(f"http://127.0.0.1:{server.port}/other", timeout=5)
        assert resp.status_code == 404
        assert server.captured is None
    finally:
        server.close()


def test_wait_returns_captured_url():
    async def _run():
        server = LoopbackCallbackServer()
        try:
            httpx.get(f"{server.redirect_uri}?code=abc", timeout=5)
            return await server.wait(timeout=5)
        finally:
            server.close()

    captured = asyncio.run(_run())
    assert captured.endswith("?code=abc")


def test_wait_timeout_raises():
    server = LoopbackCallbackServer()
    try:
        with pytest.raises(TimeoutError, match="超时"):
            asyncio.run(server.wait(timeout=0.2))
    finally:
        server.close()


def test_close_stops_serving():
    server = LoopbackCallbackServer()
    port = server.port
    server.close()
    with pytest.raises(httpx.HTTPError):
        httpx.get(f"http://127.0.0.1:{port}/callback", timeout=2)


def test_context_manager_closes_on_exit():
    with LoopbackCallbackServer() as server:
        port = server.port
        httpx.get(f"{server.redirect_uri}", timeout=5)
    # 退出 with 后服务已关闭（重试多次仍拒绝连接）
    with pytest.raises(httpx.HTTPError):
        httpx.get(f"http://127.0.0.1:{port}/anything", timeout=2)


def test_reusable_after_close():
    first = LoopbackCallbackServer()
    first.close()
    second = LoopbackCallbackServer()
    try:
        assert second.port > 0  # 新实例重新绑定可用端口
    finally:
        second.close()
