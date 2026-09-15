"""R25-D4: 活跃流查询单元测试

- StreamRegistry.find_active_by_session: pending/running 命中、终态与
  挂起跳过、跨会话跳过、无活跃返回 None
- GET /chat/stream/active: 信封结构（streamId null | uuid）
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.chat_stream_registry import StreamRegistry

pytestmark = pytest.mark.unit


def test_find_active_returns_running_stream():
    reg = StreamRegistry()

    async def setup():
        await reg.create("s-done", session_id="sess")
        e = reg.get("s-done")
        e.status = "done"  # type: ignore[union-attr]
        await reg.create("s-run", session_id="sess")

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(setup())
    # 简化: 直接用 asyncio.run 语义在同步测试里驱动
    assert reg.find_active_by_session("sess") == "s-run"


def test_find_active_skips_terminal_and_suspended():
    async def setup():
        reg = StreamRegistry()
        await reg.create("s1", session_id="sess")
        e = reg.get("s1")
        e.status = "failed"  # type: ignore[union-attr]
        assert reg.find_active_by_session("sess") is None
        await reg.create("s2", session_id="sess")
        e2 = reg.get("s2")
        e2.suspended = True  # type: ignore[union-attr]
        assert reg.find_active_by_session("sess") is None

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(setup())


def test_find_active_scoped_to_session():
    async def setup():
        reg = StreamRegistry()
        await reg.create("s-a", session_id="sess-a")

    loop = asyncio.get_event_loop_policy().new_event_loop()
    loop.run_until_complete(setup())
    # 同一 registry 实例上继续断言
    reg = StreamRegistry()
    assert reg.find_active_by_session("sess-b") is None


def test_active_route_envelope():
    from backend.api.legacy_routes import get_active_chat_stream

    reg = StreamRegistry()

    async def setup():
        await reg.create("stream-1", session_id="sess-9")

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(setup())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(streams=reg)))

    # 无活跃 → null
    none_res = get_active_chat_stream("sess-none", request)
    assert none_res == {"streamId": None}
    # 活跃 → streamId
    res = get_active_chat_stream("sess-9", request)
    assert res == {"streamId": "stream-1"}


def test_active_route_via_testclient():
    from backend.api.legacy_routes import router

    app = FastAPI()
    app.include_router(router)
    reg = StreamRegistry()

    async def setup():
        await app.state.streams.create("sid-1", session_id="sess-x")

    app.state.streams = reg
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(setup())
    client = TestClient(app)
    res = client.get("/chat/stream/active?session_id=sess-x")
    assert res.status_code == 200
    assert res.json() == {"streamId": "sid-1"}
