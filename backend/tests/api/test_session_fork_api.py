"""
M4 会话分叉路由 API 测试 — POST /api/v1/sessions/{id}/fork

真实临时 DB：
- 前缀复制在分叉点处的精确性（含 at_message_id 本身，之后的不复制）
- 缺省全量复制
- fork_root / forked_at_message_id 持久化 + list_sessions 序列化
- 标题覆盖 / 默认 "Fork: <原标题>"
- 未知会话 / 未知消息 404
"""

import time

import pytest

from backend.data.session_repo import Message as DbMessage
from backend.data.session_repo import MessageRepository, SessionRepository

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"


def _seed_messages(session_id: str, n: int = 6):
    repo = MessageRepository()
    base = 1_750_000_000_000  # 固定基准便于断言时间戳原样保留
    ids = []
    for i in range(n):
        msg_id = f"fork-seed-{i}"
        ids.append(msg_id)
        repo.save(
            DbMessage(
                id=msg_id,
                session_id=session_id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"分叉测试消息 #{i}",
                created_at=base + i * 100,
            )
        )
    return ids


@pytest.mark.asyncio()
async def test_fork_unknown_session_returns_404(client):
    resp = await client.post(f"{PREFIX}/sessions/nonexistent-id/fork", json={})
    assert resp.status_code == 404
    assert resp.json()["detail"]["type"] == "session_not_found"


@pytest.mark.asyncio()
async def test_fork_unknown_message_returns_404(client):
    create = await client.post(f"{PREFIX}/sessions", json={"title": "源会话"})
    session_id = create.json()["id"]
    _seed_messages(session_id)

    resp = await client.post(
        f"{PREFIX}/sessions/{session_id}/fork", json={"at_message_id": "no-such-msg"}
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["type"] == "message_not_found"


@pytest.mark.asyncio()
async def test_fork_prefix_copy_exactness_at_boundary(client):
    """at_message_id=fork-seed-2 → 复制 0..2（含）共 3 条，3..5 不复制。"""
    create = await client.post(f"{PREFIX}/sessions", json={"title": "边界分叉"})
    source_id = create.json()["id"]
    ids = _seed_messages(source_id)

    resp = await client.post(
        f"{PREFIX}/sessions/{source_id}/fork", json={"at_message_id": ids[2]}
    )
    assert resp.status_code == 200, resp.text
    forked = resp.json()

    assert forked["id"] != source_id
    assert forked["fork_root"] == source_id
    assert forked["forked_at_message_id"] == ids[2]
    assert forked["message_count"] == 3

    rows = MessageRepository().get_by_session(forked["id"])
    assert len(rows) == 3
    # 内容 / 顺序 / 角色 / 时间戳原样保留
    assert [r.content for r in rows] == [f"分叉测试消息 #{i}" for i in range(3)]
    assert [r.role for r in rows] == ["user", "assistant", "user"]
    assert [r.created_at for r in rows] == [1_750_000_000_000 + i * 100 for i in range(3)]
    # 新 id（不与源消息冲突）
    source_ids = {ids[0], ids[1], ids[2]}
    assert all(r.id not in source_ids for r in rows)
    # 分叉点之后的消息没有泄漏到新会话
    assert all("分叉测试消息 #3" not in r.content for r in rows)


@pytest.mark.asyncio()
async def test_fork_all_copy_default(client):
    """省略 at_message_id → 复制全部; forked_at_message_id 为 None。"""
    create = await client.post(f"{PREFIX}/sessions", json={"title": "全量分叉"})
    source_id = create.json()["id"]
    _seed_messages(source_id, n=5)

    resp = await client.post(f"{PREFIX}/sessions/{source_id}/fork", json={})
    assert resp.status_code == 200
    forked = resp.json()

    assert forked["fork_root"] == source_id
    assert forked["forked_at_message_id"] is None
    rows = MessageRepository().get_by_session(forked["id"])
    assert len(rows) == 5
    assert [r.content for r in rows] == [f"分叉测试消息 #{i}" for i in range(5)]


@pytest.mark.asyncio()
async def test_fork_title_override_and_default(client):
    """显式 title 覆盖; 缺省 title 为 "Fork: <原标题>"。"""
    create = await client.post(f"{PREFIX}/sessions", json={"title": "原始标题"})
    source_id = create.json()["id"]
    _seed_messages(source_id, n=2)

    default_fork = await client.post(f"{PREFIX}/sessions/{source_id}/fork", json={})
    assert default_fork.json()["title"] == "Fork: 原始标题"

    custom_fork = await client.post(
        f"{PREFIX}/sessions/{source_id}/fork", json={"title": "我的分支"}
    )
    assert custom_fork.json()["title"] == "我的分支"


@pytest.mark.asyncio()
async def test_list_sessions_serializes_fork_fields(client):
    """list_sessions / get_session 序列化必须带上 fork_root（侧栏徽标依赖）。"""
    create = await client.post(f"{PREFIX}/sessions", json={"title": "序列化检查"})
    source_id = create.json()["id"]
    _seed_messages(source_id, n=2)

    forked = (await client.post(f"{PREFIX}/sessions/{source_id}/fork", json={})).json()

    listing = (await client.get(f"{PREFIX}/sessions")).json()
    forked_row = next(s for s in listing if s["id"] == forked["id"])
    source_row = next(s for s in listing if s["id"] == source_id)
    assert forked_row["fork_root"] == source_id
    assert source_row["fork_root"] is None

    got = (await client.get(f"{PREFIX}/sessions/{forked['id']}")).json()
    assert got["fork_root"] == source_id
    assert "forked_at_message_id" in got


@pytest.mark.asyncio()
async def test_fork_does_not_touch_source_session(client):
    """分叉是非破坏性的：源会话消息不变。"""
    create = await client.post(f"{PREFIX}/sessions", json={"title": "源不动"})
    source_id = create.json()["id"]
    ids = _seed_messages(source_id, n=4)

    resp = await client.post(
        f"{PREFIX}/sessions/{source_id}/fork", json={"at_message_id": ids[1]}
    )
    assert resp.status_code == 200

    source_rows = MessageRepository().get_by_session(source_id)
    assert [r.id for r in source_rows] == ids
    source = SessionRepository().get(source_id)
    assert source.fork_root is None
