"""
会话 CRUD 补充测试 — 覆盖 PATCH is_pinned、PATCH 404、GET messages、POST /interrupt。

补充 test_sessions.py 缺失的边缘路径：
1. PATCH /sessions/{id} 设置 is_pinned
2. PATCH /sessions/{id} 不存在时返回 404
3. GET /sessions/{id}/messages 空列表
4. POST /interrupt 触发 agent.interrupt()
"""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"


@pytest.mark.asyncio()
async def test_update_session_pin(client):
    """PATCH /sessions/{id} 接受 is_pinned 字段更新。"""
    create_resp = await client.post(f"{PREFIX}/sessions", json={"title": "可置顶"})
    session_id = create_resp.json()["id"]

    resp = await client.patch(
        f"{PREFIX}/sessions/{session_id}",
        json={"is_pinned": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_pinned"] is True


@pytest.mark.asyncio()
async def test_update_session_unpin(client):
    """PATCH is_pinned=False 取消置顶。"""
    create_resp = await client.post(f"{PREFIX}/sessions", json={"title": "置顶会话"})
    session_id = create_resp.json()["id"]

    # 先置顶
    await client.patch(f"{PREFIX}/sessions/{session_id}", json={"is_pinned": True})
    # 再取消
    resp = await client.patch(
        f"{PREFIX}/sessions/{session_id}",
        json={"is_pinned": False},
    )
    assert resp.status_code == 200
    assert resp.json()["is_pinned"] is False


@pytest.mark.asyncio()
async def test_update_session_not_found_returns_404(client):
    """PATCH 不存在的会话返回 404。"""
    resp = await client.patch(
        f"{PREFIX}/sessions/nonexistent-session-id",
        json={"title": "新标题"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "会话不存在"


@pytest.mark.asyncio()
async def test_update_session_empty_body(client):
    """PATCH 空 body（无字段更新）仍然返回当前会话。"""
    create_resp = await client.post(f"{PREFIX}/sessions", json={"title": "空更新"})
    session_id = create_resp.json()["id"]

    resp = await client.patch(f"{PREFIX}/sessions/{session_id}", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "空更新"
    assert data["id"] == session_id


@pytest.mark.asyncio()
async def test_get_messages_empty(client):
    """新会话没有消息时返回空数组。"""
    create_resp = await client.post(f"{PREFIX}/sessions", json={"title": "空消息"})
    session_id = create_resp.json()["id"]

    resp = await client.get(f"{PREFIX}/sessions/{session_id}/messages")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio()
async def test_get_messages_returns_inserted_messages(client):
    """插入消息后可通过 GET messages 查询到。"""
    from backend.data.session_repo import Message, MessageRepository

    create_resp = await client.post(f"{PREFIX}/sessions", json={"title": "消息测试"})
    session_id = create_resp.json()["id"]

    # 手动保存两条消息
    repo = MessageRepository()
    repo.save(
        Message(
            id="m-001",
            session_id=session_id,
            role="user",
            content="你好",
            created_at=1700000000000,
        )
    )
    repo.save(
        Message(
            id="m-002",
            session_id=session_id,
            role="assistant",
            content="你好！有什么可以帮你？",
            created_at=1700000001000,
        )
    )

    resp = await client.get(f"{PREFIX}/sessions/{session_id}/messages")
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 2
    assert messages[0]["id"] == "m-001"
    assert messages[0]["role"] == "user"
    assert messages[1]["id"] == "m-002"
    assert messages[1]["role"] == "assistant"


@pytest.mark.asyncio()
async def test_interrupt_endpoint_calls_agent_interrupt(client):
    """POST /interrupt 调用 SageAgent.interrupt()。"""
    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        mock_instance = MagicMock()
        MockAgent.return_value = mock_instance

        resp = await client.post(f"{PREFIX}/interrupt")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        mock_instance.interrupt.assert_called_once()
