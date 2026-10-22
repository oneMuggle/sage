"""按路径限制请求体大小的纯 ASGI 中间件。

背景: 技能导入走 ``multipart/form-data``。Starlette 0.35 的 ``MultiPartParser``
没有 per-part / 整体字节上限(``max_part_size`` 是 0.37 才引入的),
``UploadFile`` 会先把每个 part 落盘到临时文件, 之后才轮到业务层的
1MB / 10MB 校验 —— 超限请求已经把磁盘写满了。中间件在 body 落盘前拦一道。

判定分两层:
  1. ``content-length`` 头存在 → 立即拒绝(body 尚未读取)
  2. chunked / 无 ``content-length`` → 流式计数, 累计字节超限即中止

纯 ASGI callable(非 ``BaseHTTPMiddleware``): 不引入 per-request task-group /
stream 开销, 与 ``LocalAuthMiddleware`` 的做法一致。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class MaxRequestBodyMiddleware:
    """按路径前缀限制请求体字节数, 超限直接 413。

    Args:
        app: 下游 ASGI 应用。
        limits: 路径前缀 → 最大字节数。只有命中的路径会被限制, 其余请求
            不受影响(``limits`` 为空时本中间件完全透明)。
    """

    def __init__(self, app: ASGIApp, limits: Mapping[str, int]) -> None:
        self.app = app
        self._limits: Dict[str, int] = dict(limits)

    def _limit_for(self, scope: Scope) -> Optional[int]:
        path = scope.get("path", "")
        for prefix, limit in self._limits.items():
            if path == prefix or path.startswith(prefix + "/"):
                return limit
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self._limit_for(scope)
        if limit is None:
            await self.app(scope, receive, send)
            return

        content_length = _header(scope, b"content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = None
            if declared is not None and declared > limit:
                await self._reject(scope, receive, send)
                return

        counter = _ByteCounter(limit)
        try:
            await self.app(scope, counter.wrap(receive), send)
        except _BodyTooLargeError:
            # 下游已开始读 body 但尚未写响应 → 这里补 413。
            await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "type": "payload_too_large",
                "message": "请求体超过大小限制",
            },
        )
        await response(scope, receive, send)


class _BodyTooLargeError(Exception):
    """内部信号: 流式计数超过上限。"""


class _ByteCounter:
    """包裹 ``receive``, 累计已接收字节数, 超限即抛 ``_BodyTooLargeError``。"""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._received = 0

    def wrap(self, receive: Receive) -> Receive:
        async def _receive() -> Any:
            message = await receive()
            if message["type"] == "http.request":
                self._received += len(message.get("body", b""))
                if self._received > self._limit:
                    raise _BodyTooLargeError()
            return message

        return _receive


def _header(scope: Scope, name: bytes) -> Optional[str]:
    """从 ASGI scope 的 raw headers 里取 header 值(大小写不敏感)。"""
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() == name:
            return raw_value.decode("latin-1")
    return None
