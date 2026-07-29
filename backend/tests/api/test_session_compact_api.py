"""
M4 手动压缩路由 API 测试 — POST /api/v1/sessions/{id}/compact

真实临时 DB（conftest autouse fixture）+ monkeypatch 的 LLM callable：
- 成功路径: 旧消息行被删、续接消息按正确顺序插入、计数正确
- 地板以下: no-op + reason
- 未知会话 404
- LLM 失败: DB 不被触碰
"""

import time

import pytest

from backend.chat.compaction import CONTINUATION_PREFIX
from backend.data.session_repo import Message as DbMessage, MessageRepository, SessionRepository

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"
DIGEST = "## 目标\n完成 M4 压缩测试\n## 决策\n采用全量复制\n## 关键事实\n阈值 100\n## 待办事项\n无"


def _seed_session_with_messages(n: int, content: str = "足够长的消息内容用于压缩测试" * 5):
    sess = SessionRepository().create(title="压缩测试会话")
    repo = MessageRepository()
    base = int(time.time() * 1000)
    for i in range(n):
        repo.save(
            DbMessage(
                id=f"seed-{i}",
                session_id=sess.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"{content} #{i}",
                created_at=base + i * 10,
            )
        )
    return sess


def _patch_llm(monkeypatch, callable_):
    monkeypatch.setattr(
        "backend.api.legacy_routes._build_compaction_llm_callable", lambda: callable_
    )


async def _fake_llm_ok(prompt: str) -> str:
    return DIGEST


@pytest.mark.asyncio()
async def test_compact_unknown_session_returns_404(client):
    resp = await client.post(f"{PREFIX}/sessions/nonexistent-id/compact")
    assert resp.status_code == 404


@pytest.mark.asyncio()
async def test_compact_below_message_floor_is_noop(client, monkeypatch):
    """4 条消息 < 12 地板 → compacted=false + below_message_floor, DB 不动。"""
    monkeypatch.setenv("SAGE_COMPACT_THRESHOLD", "1")
    sess = _seed_session_with_messages(4)
    _patch_llm(monkeypatch, _fake_llm_ok)

    resp = await client.post(f"{PREFIX}/sessions/{sess.id}/compact")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["compacted"] is False
    assert data["reason"] == "below_message_floor"
    assert data["before"] == 4
    assert data["after"] == 4
    assert data["removed"] == 0
    assert len(MessageRepository().get_by_session(sess.id)) == 4


@pytest.mark.asyncio()
async def test_compact_below_token_threshold_is_noop(client, monkeypatch):
    """消息数够但 token 未达阈值 → below_token_threshold。"""
    monkeypatch.setenv("SAGE_COMPACT_THRESHOLD", "999999999")
    sess = _seed_session_with_messages(14, content="短")
    _patch_llm(monkeypatch, _fake_llm_ok)

    resp = await client.post(f"{PREFIX}/sessions/{sess.id}/compact")
    assert resp.status_code == 200
    data = resp.json()
    assert data["compacted"] is False
    assert data["reason"] == "below_token_threshold"


@pytest.mark.asyncio()
async def test_compact_success_replaces_rows_and_preserves_tail(client, monkeypatch):
    """14 条 → 摘要替代前 8 条, 保留后 6 条; 续接消息排在保留尾部之前。"""
    monkeypatch.setenv("SAGE_COMPACT_THRESHOLD", "100")
    sess = _seed_session_with_messages(14)
    _patch_llm(monkeypatch, _fake_llm_ok)

    resp = await client.post(f"{PREFIX}/sessions/{sess.id}/compact")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data == {
        "ok": True,
        "compacted": True,
        "before": 14,
        "after": 7,
        "removed": 8,
    }

    rows = MessageRepository().get_by_session(sess.id)
    assert len(rows) == 7
    # 第一条是续接摘要
    assert rows[0].content.startswith(CONTINUATION_PREFIX)
    assert "完成 M4 压缩测试" in rows[0].content
    assert rows[0].role == "assistant"
    # 续接消息时间戳排在首条保留消息之前（正确排序）
    assert rows[0].created_at < rows[1].created_at
    # 尾部 6 条是原始 seed-8..seed-13（id/内容原样保留）
    assert [r.id for r in rows[1:]] == [f"seed-{i}" for i in range(8, 14)]
    # session.message_count 同步更新
    assert SessionRepository().get(sess.id).message_count == 7


@pytest.mark.asyncio()
async def test_compact_llm_failure_leaves_db_untouched(client, monkeypatch):
    """LLM 摘要失败 → ok=false + compaction_failed, 一行都不动。"""
    monkeypatch.setenv("SAGE_COMPACT_THRESHOLD", "100")
    sess = _seed_session_with_messages(14)

    async def broken_llm(prompt: str) -> str:
        raise RuntimeError("upstream exploded")

    _patch_llm(monkeypatch, broken_llm)

    resp = await client.post(f"{PREFIX}/sessions/{sess.id}/compact")
    assert resp.status_code == 502
    data = resp.json()
    assert data["ok"] is False
    assert data["error"] == "compaction_failed"

    rows = MessageRepository().get_by_session(sess.id)
    assert len(rows) == 14
    assert [r.id for r in rows] == [f"seed-{i}" for i in range(14)]


@pytest.mark.asyncio()
async def test_compact_persist_failure_rolls_back_whole_transaction(client, monkeypatch):
    """CRITICAL-1: 续接消息 INSERT 在事务中途失败（重复主键）→ 整体回滚。

    旧逐条提交流程在此场景下会永久丢失历史（删完 seed-0..7 后崩溃，
    摘要行未写入）；单事务修复后 14 条原始行全部健在，计数不变。
    """
    monkeypatch.setenv("SAGE_COMPACT_THRESHOLD", "100")
    sess = _seed_session_with_messages(14)
    SessionRepository().update(sess.id, message_count=14)
    _patch_llm(monkeypatch, _fake_llm_ok)

    # 让续接消息 id 与保留消息 seed-8 撞主键：8 条 DELETE 已执行后
    # INSERT 抛 IntegrityError → rollback 必须恢复全部删除。
    class _FixedUUID:
        def __str__(self):
            return "seed-8"

    monkeypatch.setattr("backend.api.legacy_routes.uuid.uuid4", lambda: _FixedUUID())

    resp = await client.post(f"{PREFIX}/sessions/{sess.id}/compact")
    assert resp.status_code == 502
    data = resp.json()
    assert data["ok"] is False
    assert data["error"] == "persist_failed"

    rows = MessageRepository().get_by_session(sess.id)
    assert [r.id for r in rows] == [f"seed-{i}" for i in range(14)]
    assert SessionRepository().get(sess.id).message_count == 14


@pytest.mark.asyncio()
async def test_compact_concurrent_reentry_returns_409(client, monkeypatch):
    """MEDIUM-1 后端兜底：同会话重复触发压缩 → 409 compact_in_progress，DB 不动。"""
    monkeypatch.setenv("SAGE_COMPACT_THRESHOLD", "100")
    sess = _seed_session_with_messages(14)
    _patch_llm(monkeypatch, _fake_llm_ok)

    from backend.api import legacy_routes

    legacy_routes._compact_in_progress.add(sess.id)
    try:
        resp = await client.post(f"{PREFIX}/sessions/{sess.id}/compact")
    finally:
        legacy_routes._compact_in_progress.discard(sess.id)

    assert resp.status_code == 409
    data = resp.json()
    assert data["ok"] is False
    assert data["error"] == "compact_in_progress"
    assert len(MessageRepository().get_by_session(sess.id)) == 14


@pytest.mark.asyncio()
async def test_compact_without_llm_config_returns_error(client, monkeypatch):
    """没有可用 LLM 配置 → ok=false + llm_not_configured。"""
    monkeypatch.setenv("SAGE_COMPACT_THRESHOLD", "100")
    sess = _seed_session_with_messages(14)
    _patch_llm(monkeypatch, None)

    resp = await client.post(f"{PREFIX}/sessions/{sess.id}/compact")
    assert resp.status_code == 502
    data = resp.json()
    assert data["ok"] is False
    assert data["error"] == "llm_not_configured"
    assert len(MessageRepository().get_by_session(sess.id)) == 14
