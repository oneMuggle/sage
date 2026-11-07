"""独立端口的 MCP 监听器（默认 ``127.0.0.1:8767``，默认关闭）。

与主 API（8765，带 local_auth）完全隔离：不同 FastAPI 实例、不同端口、
不挂载任何 CORS 中间件。只绑定回环地址；公网访问经 Electron 管理的
cloudflared Quick Tunnel 转发。
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from . import DEFAULT_PORT, SERVER_VERSION
from .protocol import RemoteMcpService

logger = logging.getLogger(__name__)

LOOPBACK = "127.0.0.1"


def create_app(service: RemoteMcpService) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse(
            {"service": "SageWorkspaceMCP", "version": SERVER_VERSION,
             "status": "paused" if service.paused else "ready", "transport": "streamable-http"},
            status_code=503 if service.paused else 200,
        )

    @app.api_route("/mcp/{token}", methods=["GET", "POST", "DELETE"])
    async def mcp_endpoint(token: str, request: Request) -> Response:
        body = await request.body()
        headers = {k.lower(): v for k, v in request.headers.items()}
        status, extra, payload = await run_in_threadpool(
            service.handle, request.method, token, headers, body
        )
        if payload is None:
            return Response(status_code=status, headers=extra)
        return JSONResponse(payload, status_code=status, headers=extra)

    return app


class Listener:
    """在后台线程里运行 uvicorn；``start`` / ``stop`` 可重复调用。"""

    def __init__(self, service: RemoteMcpService) -> None:
        self.service = service
        self.port: Optional[int] = None
        self._server = None
        self._thread: Optional[threading.Thread] = None
        self.error: Optional[str] = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, port: int = DEFAULT_PORT) -> int:
        if self.running:
            return self.port or port
        import uvicorn

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex((LOOPBACK, port)) == 0:
                raise OSError(f"端口 {port} 已被占用")
        config = uvicorn.Config(create_app(self.service), host=LOOPBACK, port=port,
                                log_config=None, access_log=False, lifespan="off")
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
        self._server = server
        self.error = None

        def _run() -> None:
            try:
                server.run()
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
                logger.warning("remote MCP listener crashed: %s", exc)

        self._thread = threading.Thread(target=_run, name="remote-mcp-listener", daemon=True)
        self._thread.start()
        deadline = time.time() + 5
        while time.time() < deadline and not getattr(server, "started", False):
            if not self._thread.is_alive():
                raise OSError(self.error or "监听器启动失败")
            time.sleep(0.05)
        self.port = port
        self.service.audit.record("listener.started", port=port)
        return port

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None
        if self.port is not None:
            self.service.audit.record("listener.stopped", port=self.port)
        self.port = None


__all__ = ["LOOPBACK", "Listener", "create_app"]
