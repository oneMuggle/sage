"""MaxRequestBodyMiddleware 单测。

覆盖两条判定路径:
  - content-length 头 > limit → 立即 413, 不读 body
  - 无 content-length → 流式计数, 累计字节超限 → 413

也验证未命中的路径不受影响、命中但字节合法时透传。
"""

from __future__ import annotations

import asyncio
from typing import List, Tuple

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from backend.api.request_body_limit import (
    MaxRequestBodyMiddleware,
    _BodyTooLargeError,
    _ByteCounter,
)

pytestmark = pytest.mark.unit


_LIMIT = 16


async def _echo(request: Request) -> JSONResponse:
    body = await request.body()
    return JSONResponse({"bytes": len(body)})


def _app(path: str = "/upload") -> Starlette:
    routes = [Route(path, _echo, methods=["POST"])]
    app = Starlette(routes=routes)
    app.add_middleware(MaxRequestBodyMiddleware, limits={path: _LIMIT})
    return app


def test_content_length_over_limit_returns_413() -> None:
    """content-length > limit → 立即 413, 不下游。"""
    client = TestClient(_app())
    body = b"x" * (_LIMIT + 1)
    resp = client.post("/upload", content=body)
    assert resp.status_code == 413
    assert resp.json()["type"] == "payload_too_large"


def test_unmatched_path_not_limited() -> None:
    """未命中的路径不受限制。"""
    client = TestClient(_app(path="/upload"))
    big = b"x" * (_LIMIT * 4)
    resp = client.post("/different", content=big)
    # /different 没注册路由 → Starlette 404, 不是 413
    assert resp.status_code == 404


def test_matched_path_under_limit_passes() -> None:
    """命中路径 + body 合法 → 下游处理。"""
    client = TestClient(_app())
    body = b"x" * (_LIMIT - 1)
    resp = client.post("/upload", content=body)
    assert resp.status_code == 200
    assert resp.json()["bytes"] == _LIMIT - 1


def test_matched_path_at_exact_limit_passes() -> None:
    """body 字节 == limit → 允许(<=, 不是 <)。"""
    client = TestClient(_app())
    resp = client.post("/upload", content=b"x" * _LIMIT)
    assert resp.status_code == 200
    assert resp.json()["bytes"] == _LIMIT


def test_streaming_counter_raises_over_limit() -> None:
    """_ByteCounter: 累计字节 > limit → 抛 _BodyTooLarge。"""

    async def _drive() -> Tuple[int, bool]:
        counter = _ByteCounter(_LIMIT)
        wrapped = counter.wrap(_make_receive([b"x" * 8, b"x" * 16]))
        received = 0
        raised = False
        try:
            while True:
                msg = await wrapped()
                if msg["type"] == "http.disconnect":
                    break
                received += len(msg.get("body", b""))
        except _BodyTooLargeError:
            raised = True
        return received, raised

    received, raised = asyncio.run(_drive())
    assert raised is True
    # 累计到 24 时才抛(前 8 字节合法, 后 16 字节触发)
    assert received == 8


def _make_receive(chunks: List[bytes]):
    """构造一个返回 chunk 列表、最后返回 disconnect 的 async receive。"""
    it = iter(chunks + [None])

    async def _receive() -> dict:
        chunk = next(it)
        if chunk is None:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": chunk, "more_body": True}

    return _receive
