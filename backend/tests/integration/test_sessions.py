"""
会话 CRUD 测试
"""

import pytest

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_create_session(client):
    """创建新会话"""
    resp = await client.post(f"{PREFIX}/sessions", json={"title": "测试对话"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "测试对话"
    assert "id" in data
    assert data["message_count"] == 0


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_list_sessions_empty(client):
    """空列表返回空数组"""
    resp = await client.get(f"{PREFIX}/sessions")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_list_sessions_after_create(client):
    """创建后可在列表中看到"""
    await client.post(f"{PREFIX}/sessions", json={"title": "对话A"})
    await client.post(f"{PREFIX}/sessions", json={"title": "对话B"})

    resp = await client.get(f"{PREFIX}/sessions")
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) == 2
    titles = [s["title"] for s in sessions]
    assert "对话A" in titles
    assert "对话B" in titles


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_get_session(client):
    """获取单个会话"""
    create_resp = await client.post(f"{PREFIX}/sessions", json={"title": "获取测试"})
    session_id = create_resp.json()["id"]

    resp = await client.get(f"{PREFIX}/sessions/{session_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "获取测试"
    assert data["id"] == session_id


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_get_session_not_found(client):
    """不存在的会话返回 404"""
    resp = await client.get(f"{PREFIX}/sessions/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_update_session(client):
    """更新会话标题"""
    create_resp = await client.post(f"{PREFIX}/sessions", json={"title": "旧标题"})
    session_id = create_resp.json()["id"]

    resp = await client.patch(f"{PREFIX}/sessions/{session_id}", json={"title": "新标题"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "新标题"


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_delete_session(client):
    """删除会话"""
    create_resp = await client.post(f"{PREFIX}/sessions", json={"title": "待删除"})
    session_id = create_resp.json()["id"]

    resp = await client.delete(f"{PREFIX}/sessions/{session_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # 确认已删除
    resp = await client.get(f"{PREFIX}/sessions/{session_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_delete_nonexistent_session(client):
    """删除不存在的会话返回 404"""
    resp = await client.delete(f"{PREFIX}/sessions/nonexistent-id")
    assert resp.status_code == 404
