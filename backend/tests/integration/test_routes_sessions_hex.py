"""验证 hex_routes 新增 6 个 sessions 端点 (PG-A1 GREEN-2)。

本文件专门测 hex 路径下 6 端点行为,要求 API_MODE=hex。
legacy 模式 (default since PG-A1 GREEN-2) 不走 hex_routes,本文件全部 skip。

DI 装配:用 ``hex_sessions_client`` fixture override  ``get_session_service``
工厂为真实 ``SessionService`` 实例;teardown 还原避免污染同 ``app`` 上的
其它测试。
"""

import os
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.adapters.out.event.stdout_adapter import StdoutEventAdapter
from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
from backend.api.hex_routes import get_session_service
from backend.application.services.session_service import SessionService
from backend.main import app

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"

# 本文件专门测 hex 路径;legacy 模式下本模块的 6 端点不被注册
_API_MODE = os.environ.get("API_MODE", "legacy").lower()  # PG-A1: default legacy
_HEX_ONLY = pytest.mark.skipif(
    _API_MODE != "hex",
    reason=f"本文件测 hex 6 sessions 端点;当前 API_MODE={_API_MODE!r}(需 hex)",
)


@pytest_asyncio.fixture
async def hex_sessions_client():
    """自带 DI override 的异步客户端 + 真实 SessionService 实例。

    装配:storage=MemoryStorageAdapter,metrics=NoopMetricAdapter,
    events=StdoutEventAdapter(verbose=False)。fixture 退出时还原
    ``app.dependency_overrides`` 避免污染后续测试。
    """
    fake_svc = SessionService(
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=StdoutEventAdapter(verbose=False),
    )

    saved_override = app.dependency_overrides.get(get_session_service)
    app.dependency_overrides[get_session_service] = lambda: fake_svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac, fake_svc
    finally:
        if saved_override is not None:
            app.dependency_overrides[get_session_service] = saved_override
        else:
            app.dependency_overrides.pop(get_session_service, None)


# ==================== POST /sessions ====================


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_post_sessions_creates_and_returns_dict(hex_sessions_client):
    """POST /sessions 创建会话,返回 dict 包含 id + title (匹配 legacy 契约)。"""
    ac, _ = hex_sessions_client
    resp = await ac.post(f"{PREFIX}/sessions", json={"title": "我的新会话"})
    assert resp.status_code == 200
    data: dict[str, Any] = resp.json()
    assert "id" in data
    assert data["title"] == "我的新会话"


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_post_sessions_default_title(hex_sessions_client):
    """未传 title 时使用 SessionCreate 默认值。"""
    ac, _ = hex_sessions_client
    resp = await ac.post(f"{PREFIX}/sessions", json={})
    assert resp.status_code == 200
    assert resp.json()["title"] == "新对话"


# ==================== GET /sessions ====================


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_get_sessions_lists_created(hex_sessions_client):
    """GET /sessions 列出已创建的会话。"""
    ac, _ = hex_sessions_client
    await ac.post(f"{PREFIX}/sessions", json={"title": "A"})
    await ac.post(f"{PREFIX}/sessions", json={"title": "B"})
    resp = await ac.get(f"{PREFIX}/sessions")
    assert resp.status_code == 200
    data = resp.json()
    titles = {s["title"] for s in data}
    assert "A" in titles
    assert "B" in titles


# ==================== GET /sessions/{id} ====================


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_get_session_returns_dict(hex_sessions_client):
    """GET /sessions/{id} 返单个 dict。"""
    ac, _ = hex_sessions_client
    create = await ac.post(f"{PREFIX}/sessions", json={"title": "fetch"})
    sid = create.json()["id"]
    resp = await ac.get(f"{PREFIX}/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "fetch"
    assert resp.json()["id"] == sid


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_get_session_404_when_missing(hex_sessions_client):
    """GET 不存在会话返 404 + '会话不存在' detail (匹配 legacy 错误文案)。"""
    ac, _ = hex_sessions_client
    resp = await ac.get(f"{PREFIX}/sessions/nonexistent-id")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "会话不存在"


# ==================== PATCH /sessions/{id} ====================


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_patch_session_updates_title(hex_sessions_client):
    """PATCH 改 title 生效,响应返新值。"""
    ac, _ = hex_sessions_client
    create = await ac.post(f"{PREFIX}/sessions", json={"title": "旧"})
    sid = create.json()["id"]
    resp = await ac.patch(f"{PREFIX}/sessions/{sid}", json={"title": "新"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "新"


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_patch_session_404_when_missing(hex_sessions_client):
    """PATCH 不存在会话返 404。"""
    ac, _ = hex_sessions_client
    resp = await ac.patch(
        f"{PREFIX}/sessions/nonexistent-id", json={"title": "x"}
    )
    assert resp.status_code == 404


# ==================== DELETE /sessions/{id} ====================


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_delete_session_returns_status_ok(hex_sessions_client):
    """DELETE 成功返 {"status": "ok"} (匹配 legacy 契约)。"""
    ac, _ = hex_sessions_client
    create = await ac.post(f"{PREFIX}/sessions", json={"title": "del"})
    sid = create.json()["id"]
    resp = await ac.delete(f"{PREFIX}/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_delete_session_404_when_missing(hex_sessions_client):
    """DELETE 不存在会话返 404。"""
    ac, _ = hex_sessions_client
    resp = await ac.delete(f"{PREFIX}/sessions/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_delete_session_decrements_counter(hex_sessions_client):
    """删除已存在会话后,active_sessions 计数应回到 0。"""
    ac, fake_svc = hex_sessions_client
    create = await ac.post(f"{PREFIX}/sessions", json={"title": "t"})
    sid = create.json()["id"]
    assert fake_svc._active_session_count == 1
    await ac.delete(f"{PREFIX}/sessions/{sid}")
    assert fake_svc._active_session_count == 0


# ==================== GET /sessions/{id}/messages ====================


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_get_messages_empty_for_new_session(hex_sessions_client):
    """新会话无消息,GET messages 返空 list。"""
    ac, _ = hex_sessions_client
    create = await ac.post(f"{PREFIX}/sessions", json={"title": "empty"})
    sid = create.json()["id"]
    resp = await ac.get(f"{PREFIX}/sessions/{sid}/messages")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_get_messages_returns_dicts(hex_sessions_client):
    """GET messages 返 list[dict],每条含 role + content。"""
    ac, fake_svc = hex_sessions_client
    from backend.domain.message import Message, Role

    create = await ac.post(f"{PREFIX}/sessions", json={"title": "chat"})
    sid = create.json()["id"]
    # 通过 service 直接追加消息(hex 端点没有 POST message 端点,
    # 那属于后续 PR;此处用 storage 走真实路径覆盖)
    await fake_svc.storage.append_message(sid, Message(role=Role.USER, content="hi"))
    await fake_svc.storage.append_message(
        sid, Message(role=Role.ASSISTANT, content="hello")
    )
    resp = await ac.get(f"{PREFIX}/sessions/{sid}/messages")
    assert resp.status_code == 200
    msgs = resp.json()
    assert len(msgs) == 2
    assert msgs[0]["content"] == "hi"
    assert msgs[1]["content"] == "hello"
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
