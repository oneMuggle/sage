"""
delete_message 路由集成测试 — 覆盖 POST /messages/{id}/delete 端点。

对应 Tauri command `delete_message`（PR-2）:
- 现有消息 → 200 + {"deleted": true}
- 不存在消息 → 404 + 结构化 detail
- 重复删除 → 第二次 404 (幂等性)
- 验证消息真的从数据库消失（不只是 API 假装）
"""

import pytest

# 依赖 SessionService DI（删除消息时需查 session 存在），main.py 未装配（未来 PR）。
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        True,
        reason="get_session_service() DI 未装配（hex_routes.py:282-283 未来工作）",
    ),
]

PREFIX = "/api/v1"


def _insert_message(client, session_id: str, message_id: str, content: str = "test") -> None:
    """工具函数: 绕过 chat API, 直接往 DB 插一条消息, 模拟历史消息。"""
    from backend.data.session_repo import Message, MessageRepository

    MessageRepository().save(
        Message(
            id=message_id,
            session_id=session_id,
            role="user",
            content=content,
            created_at=1700000000000,
        )
    )


@pytest.mark.asyncio()
async def test_delete_existing_message_returns_deleted_true(client):
    """存在消息 → 200 + {\"deleted\": true}."""
    create_resp = await client.post(f"{PREFIX}/sessions", json={"title": "消息删除测试"})
    session_id = create_resp.json()["id"]
    _insert_message(client, session_id, "m-del-001", "可删除")

    resp = await client.post(f"{PREFIX}/messages/m-del-001/delete")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"deleted": True}


@pytest.mark.asyncio()
async def test_delete_missing_message_returns_404(client):
    """不存在的 message_id → 404 + 结构化 detail (前端可分类处理)."""
    resp = await client.post(f"{PREFIX}/messages/m-nonexistent/delete")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["type"] == "message_not_found"
    assert "m-nonexistent" in detail["message"]


@pytest.mark.asyncio()
async def test_delete_message_idempotency_returns_404_on_second_call(client):
    """第二次删同一 id → 404 (不是 200, 不是 500)."""
    create_resp = await client.post(f"{PREFIX}/sessions", json={"title": "幂等测试"})
    session_id = create_resp.json()["id"]
    _insert_message(client, session_id, "m-idem-001", "可删一次")

    # 第一次删除
    first = await client.post(f"{PREFIX}/messages/m-idem-001/delete")
    assert first.status_code == 200
    assert first.json() == {"deleted": True}

    # 第二次删除相同 id
    second = await client.post(f"{PREFIX}/messages/m-idem-001/delete")
    assert second.status_code == 404
    assert second.json()["detail"]["type"] == "message_not_found"


@pytest.mark.asyncio()
async def test_delete_message_removes_row_from_db(client):
    """删除后 GET /sessions/{id}/messages 不再列出该消息 — 物理删除不是软删."""
    create_resp = await client.post(f"{PREFIX}/sessions", json={"title": "物理删除验证"})
    session_id = create_resp.json()["id"]
    _insert_message(client, session_id, "m-phys-001", "要被物理删")
    _insert_message(client, session_id, "m-phys-002", "留")

    # 删除前: 2 条
    list_before = await client.get(f"{PREFIX}/sessions/{session_id}/messages")
    assert list_before.status_code == 200
    assert {m["id"] for m in list_before.json()} == {"m-phys-001", "m-phys-002"}

    # 删除 m-phys-001
    del_resp = await client.post(f"{PREFIX}/messages/m-phys-001/delete")
    assert del_resp.status_code == 200

    # 删除后: 只剩 m-phys-002
    list_after = await client.get(f"{PREFIX}/sessions/{session_id}/messages")
    assert list_after.status_code == 200
    remaining_ids = {m["id"] for m in list_after.json()}
    assert remaining_ids == {"m-phys-002"}
    assert "m-phys-001" not in remaining_ids


@pytest.mark.asyncio()
async def test_delete_message_does_not_affect_other_sessions_messages(client):
    """删一个会话里的消息不应影响其他会话."""
    from backend.data.session_repo import Message, MessageRepository

    s1 = (await client.post(f"{PREFIX}/sessions", json={"title": "S1"})).json()["id"]
    s2 = (await client.post(f"{PREFIX}/sessions", json={"title": "S2"})).json()["id"]

    repo = MessageRepository()
    repo.save(Message(id="m-s1", session_id=s1, role="user", content="S1 消息", created_at=1))
    repo.save(Message(id="m-s2", session_id=s2, role="user", content="S2 消息", created_at=2))

    # 删 S1 的 m-s1
    resp = await client.post(f"{PREFIX}/messages/m-s1/delete")
    assert resp.status_code == 200

    # S2 的 m-s2 仍然在
    s2_list = await client.get(f"{PREFIX}/sessions/{s2}/messages")
    assert s2_list.status_code == 200
    assert {m["id"] for m in s2_list.json()} == {"m-s2"}
