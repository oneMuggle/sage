"""MCP OAuth loopback 回调监听（切片 3b，r63）。

RFC 8252 §7 loopback redirect：本机 127.0.0.1 随机端口起一次性 HTTP
服务，捕获授权服务器的重定向完整 URL。redirect_uri 必须在注册/授权前
确定，所以先 ``LoopbackCallbackServer()`` 拿端口，再把它交给
:func:`authorize_mcp_server_with_loopback` 完成整条授权流。

stdlib only（http.server / threading），与切片 1-3a 同口径。
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Optional

from backend.mcp.oauth import authorize_mcp_server

#: 授权完成后用户在浏览器看到的提示页
_SUCCESS_HTML = (
    "<!doctype html><html><head><meta charset='utf-8'>"
    "<title>Sage 授权完成</title></head><body style='font-family:sans-serif;"
    "text-align:center;padding-top:4em'>"
    "<h2>授权完成 ✓</h2><p>请回到 Sage 继续使用。</p>"
    "</body></html>"
)


class _CallbackHandler(BaseHTTPRequestHandler):
    """单次 GET /callback 捕获完整 URL；其余路径 404。"""

    server_version = "SageOAuthLoopback/1"

    def do_GET(self) -> None:  # noqa: N802 — http.server 命名约定
        server: "LoopbackCallbackServer" = self.server.sage_oauth_owner  # type: ignore[attr-defined]
        if self.path.startswith("/callback"):
            server._captured = (
                f"http://127.0.0.1:{server.port}{self.path}"
            )
            self._respond_html(_SUCCESS_HTML)
        else:
            self._respond_html("<h1>404</h1>", status=404)

    def _respond_html(self, html: str, status: int = 200) -> None:
        payload = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return  # 静默访问日志


class LoopbackCallbackServer:
    """一次性 loopback 回调服务（127.0.0.1 随机端口）。"""

    def __init__(self) -> None:
        self._server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
        self._server.sage_oauth_owner = self  # handler 回写捕获结果
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
        )
        self._thread.start()
        self._captured: Optional[str] = None

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.port}/callback"

    @property
    def captured(self) -> Optional[str]:
        return self._captured

    async def wait(self, timeout: float = 300.0) -> str:
        """等待回调 URL；超时抛 TimeoutError。"""
        import asyncio

        deadline = asyncio.get_event_loop().time() + timeout
        while self._captured is None:
            if asyncio.get_event_loop().time() > deadline:
                raise TimeoutError(f"等待 OAuth 回调超时（{timeout:.0f}s）")
            await asyncio.sleep(0.05)
        return self._captured

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> "LoopbackCallbackServer":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


async def authorize_mcp_server_with_loopback(
    server_url: str,
    *,
    scope: Optional[str] = None,
    resource: Optional[str] = None,
    client_name: str = "sage",
    http_get_json: Any,
    http_post_json: Any,
    open_url: Callable[[str], object],
    callback_timeout: float = 300.0,
) -> Any:
    """loopback 版完整授权：回听 → 拉起浏览器 → 捕获回调 → 走 3a 编排。

    ``open_url(authorization_url)``：真实环境传 ``webbrowser.open``；
    返回 False 或抛错 → 立即失败（不让用户对着死等）。
    """
    with LoopbackCallbackServer() as loopback:

        async def wait_for_callback(authorization_url: str) -> str:
            opened = open_url(authorization_url)
            if opened is False:
                raise RuntimeError("浏览器拉起失败（open_url 返回 False）")
            return await loopback.wait(timeout=callback_timeout)

        return await authorize_mcp_server(
            server_url,
            redirect_uri=loopback.redirect_uri,
            scope=scope,
            resource=resource,
            client_name=client_name,
            http_get_json=http_get_json,
            http_post_json=http_post_json,
            wait_for_callback=wait_for_callback,
        )
