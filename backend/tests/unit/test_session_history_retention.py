"""非破坏性会话压缩（长对话完整历史）回归测试。

背景：压缩此前物理删除消息前缀（只留最近 6 条 + 摘要），会话页面看不到完整记录。
新契约：
- 压缩后原始消息保留（``compacted_at`` 非空 = 仅展示）；
- LLM 上下文（get_active_segment / db_rows_to_history / events_to_history）
  仍然只含「摘要续接行 + 未压缩消息」；
- 存量归档可幂等回填回主会话。
"""

import json
import sqlite3
import time

import pytest

from backend.data.session_repo import Message, MessageRepository, SessionRepository

pytestmark = pytest.mark.unit


def _seed_messages(repo: MessageRepository, session_id: str, n: int = 4) -> int:
    base = int(time.time() * 1000)
    for i in range(n):
        repo.save(
            Message(
                id=f"m{i}",
                session_id=session_id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"内容 {i}",
                created_at=base + i,
            )
        )
    return base


def _compact(
    repo: MessageRepository,
    session_id: str,
    prefix_ids: list,
    continuation_created_at: int,
) -> None:
    repo.replace_prefix_with_continuation(
        session_id,
        prefix_ids,
        Message(
            id="cont-1",
            session_id=session_id,
            role="assistant",
            content="[上下文已压缩] 此前对话摘要：测试摘要",
            created_at=continuation_created_at,
            compact_info=json.dumps({"before": 4, "after": 3, "removed": 2}),
        ),
    )


def test_compaction_retains_prefix_rows_as_display_history(setup_test_db):
    session = SessionRepository().create(title="retain-history")
    repo = MessageRepository()
    base = _seed_messages(repo, session.id, 4)

    _compact(repo, session.id, ["m0", "m1"], base + 1)

    rows = repo.get_by_session(session.id)
    # 会话页面（get_by_session）拿到完整历史：原 4 条 + 续接行
    assert [r.id for r in rows] == ["m0", "m1", "cont-1", "m2", "m3"]
    by_id = {r.id: r for r in rows}
    # 被压缩的前缀行保留，但标记为仅展示
    assert by_id["m0"].compacted_at is not None
    assert by_id["m1"].compacted_at is not None
    # 保留尾部和续接行仍属模型可见上下文
    assert by_id["m2"].compacted_at is None
    assert by_id["cont-1"].compacted_at is None
    # 会话计数按实际行数落库
    assert SessionRepository().get(session.id).message_count == 5
    # 序列化面暴露标记（前端/导出可用）
    assert by_id["m0"].to_dict()["compacted_at"] is not None


def test_get_active_segment_excludes_compacted_rows(setup_test_db):
    session = SessionRepository().create(title="active-segment")
    repo = MessageRepository()
    base = _seed_messages(repo, session.id, 4)
    _compact(repo, session.id, ["m0", "m1"], base + 1)

    active = repo.get_active_segment(session.id)
    # LLM 上下文不含压缩行
    assert [r.id for r in active] == ["cont-1", "m2", "m3"]


def test_db_rows_to_history_excludes_compacted_rows(setup_test_db):
    from backend.chat.history_context import db_rows_to_history

    session = SessionRepository().create(title="history-projection")
    repo = MessageRepository()
    base = _seed_messages(repo, session.id, 4)
    _compact(repo, session.id, ["m0", "m1"], base + 1)

    history = db_rows_to_history(repo.get_by_session(session.id))
    assert [h["content"] for h in history] == [
        "[上下文已压缩] 此前对话摘要：测试摘要",
        "内容 2",
        "内容 3",
    ]


def test_event_projection_skips_compacted_appended_event():
    from backend.chat.event_projection import events_to_history
    from backend.data.session_event_repo import EVENT_MESSAGE_APPENDED

    events = [
        {
            "type": EVENT_MESSAGE_APPENDED,
            "payload": {
                "id": "forked-old",
                "role": "user",
                "content": "旧消息",
                "compacted_at": 1700000000,
            },
        },
        {
            "type": EVENT_MESSAGE_APPENDED,
            "payload": {"id": "cont", "role": "assistant", "content": "摘要"},
        },
    ]
    assert events_to_history(events) == [{"role": "assistant", "content": "摘要"}]


def test_chat_service_filters_compacted_history():
    """hex 路径 ChatService 从 storage 拉历史时同样剔除展示行。"""
    from backend.application.services.chat_service import _model_visible_history
    from backend.domain.message import Message as DomainMessage, Role

    visible = DomainMessage(role=Role.USER, content="新消息")
    hidden = DomainMessage(
        role=Role.USER, content="旧消息", compacted_at=1700000000000
    )
    assert _model_visible_history([hidden, visible]) == [visible]


def test_sqlite_adapter_maps_compacted_at():
    """storage 适配器必须把 compacted_at 映射到 domain Message。"""
    from backend.adapters.out.storage.sqlite_adapter import _data_to_domain_message
    from backend.data.session_repo import Message as DbMessage

    row = DbMessage(
        id="m1",
        session_id="s1",
        role="user",
        content="hi",
        created_at=1,
        compacted_at=1700000000000,
    )
    assert _data_to_domain_message(row).compacted_at == 1700000000000


def test_migration_adds_compacted_at_and_needs_restore_columns(setup_test_db):
    import backend.data.database as db_mod

    db = db_mod.get_database()
    conn = db.get_connection()
    msg_cols = [r["name"] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
    assert "compacted_at" in msg_cols
    lineage_cols = [
        r["name"] for r in conn.execute("PRAGMA table_info(session_lineage)").fetchall()
    ]
    assert "needs_restore" in lineage_cols

    # 幂等：再跑一次 init_db 不抛 duplicate column
    db.init_db()
    msg_cols_again = [
        r["name"] for r in conn.execute("PRAGMA table_info(messages)").fetchall()
    ]
    assert msg_cols_again.count("compacted_at") == 1


def test_compaction_failure_rolls_back_marking_and_archive(setup_test_db):
    """续接行插入失败（主键冲突）→ 前缀标记 / 归档 / 计数整体回滚。"""
    from backend.data.session_lineage import list_archives

    session = SessionRepository().create(title="rollback")
    repo = MessageRepository()
    base = _seed_messages(repo, session.id, 4)

    with pytest.raises(sqlite3.IntegrityError):
        # 续接行 id 与既有 m2 冲突 → INSERT 抛 IntegrityError
        repo.replace_prefix_with_continuation(
            session.id,
            ["m0", "m1"],
            Message(
                id="m2",
                session_id=session.id,
                role="assistant",
                content="冲突的续接行",
                created_at=base + 1,
            ),
        )

    rows = repo.get_by_session(session.id)
    assert [r.id for r in rows] == ["m0", "m1", "m2", "m3"]
    assert all(r.compacted_at is None for r in rows)
    assert list_archives(setup_test_db, session.id) == []


def test_init_db_retries_pending_backfill(setup_test_db):
    """迁移已应用但仍有 needs_restore=1 的行时，下次启动应继续回填。"""
    from backend.data.session_lineage import archive_prefix_in_transaction
    from backend.data.session_repo import Message as DbMessage

    db = setup_test_db
    session = SessionRepository().create(title="retry-backfill")
    repo = MessageRepository()
    base = 1700000000000
    for i, text in enumerate(["内容 0", "内容 1", "内容 2"]):
        repo.save(
            DbMessage(
                id=f"m{i}",
                session_id=session.id,
                role="user",
                content=text,
                created_at=base + i * 2,
            )
        )

    conn = db.get_connection()
    cursor = conn.cursor()
    archive_prefix_in_transaction(
        cursor,
        session.id,
        ["m0", "m1"],
        reason="compaction",
        now_ms=base + 1,
        needs_restore=True,
    )
    cursor.execute("DELETE FROM messages WHERE id IN ('m0', 'm1')")
    cursor.execute(
        "INSERT INTO messages (id, session_id, role, content, created_at) "
        "VALUES ('cont-retry', ?, 'assistant', '[上下文已压缩] 摘要', ?)",
        (session.id, base + 3),
    )
    conn.commit()

    # 模拟"上次回填失败"：needs_restore 仍为 1；再次启动触发重试
    db.init_db()

    rows = repo.get_by_session(session.id)
    assert len(rows) == 4
    assert [r.content for r in rows] == ["内容 0", "内容 1", "[上下文已压缩] 摘要", "内容 2"]
    assert all(r.compacted_at is not None for r in rows[:2])


def test_restore_orders_prefix_before_summary_on_timestamp_tie(setup_test_db):
    """回填行与续接摘要 created_at 相同（连续毫秒）时，前缀仍排在摘要之前。"""
    from backend.data.session_lineage import (
        archive_prefix_in_transaction,
        restore_compacted_history,
    )

    db = setup_test_db
    session = SessionRepository().create(title="tie-order")
    repo = MessageRepository()
    base = 1700000000000
    # 步长 1：m1.created_at == 续接摘要 created_at（首条保留 m2 - 1）
    for i, text in enumerate(["内容 0", "内容 1", "内容 2"]):
        repo.save(
            Message(
                id=f"m{i}",
                session_id=session.id,
                role="user",
                content=text,
                created_at=base + i,
            )
        )

    conn = db.get_connection()
    cursor = conn.cursor()
    archive_prefix_in_transaction(
        cursor,
        session.id,
        ["m0", "m1"],
        reason="compaction",
        now_ms=base + 1,
        needs_restore=True,
    )
    cursor.execute("DELETE FROM messages WHERE id IN ('m0', 'm1')")
    cursor.execute(
        "INSERT INTO messages (id, session_id, role, content, created_at) "
        "VALUES ('cont-tie', ?, 'assistant', '[上下文已压缩] 旧摘要', ?)",
        (session.id, base + 1),  # 与 m1 同毫秒
    )
    conn.commit()

    restore_compacted_history(db)

    rows = repo.get_by_session(session.id)
    assert [r.content for r in rows] == [
        "内容 0",
        "内容 1",
        "[上下文已压缩] 旧摘要",
        "内容 2",
    ]


def test_restore_compacted_history_is_idempotent(setup_test_db):
    """旧式破坏性压缩的归档前缀可回填回主会话，且重复执行不重复。"""
    from backend.data.session_lineage import (
        archive_prefix_in_transaction,
        restore_compacted_history,
    )

    db = setup_test_db
    session = SessionRepository().create(title="legacy-compacted")
    repo = MessageRepository()
    # 步长 2，给续接行留插入空间：前缀 m0(base+0),m1(base+2)；续接行
    # 落在首条保留消息 m2(base+4) 之前 = base+3；符合 _persist_compaction 约定。
    base = 1700000000000
    for i, text in enumerate(["内容 0", "内容 1", "内容 2"]):
        repo.save(
            Message(
                id=f"m{i}",
                session_id=session.id,
                role="user" if i % 2 == 0 else "assistant",
                content=text,
                created_at=base + i * 2,
            )
        )

    # 模拟旧版：前缀先归档，再从主会话物理删除，插入续接摘要
    conn = db.get_connection()
    cursor = conn.cursor()
    archive_prefix_in_transaction(
        cursor,
        session.id,
        ["m0", "m1"],
        reason="compaction",
        now_ms=1700000099000,
        needs_restore=True,
    )
    cursor.execute("DELETE FROM messages WHERE id IN ('m0', 'm1')")
    cursor.execute(
        "INSERT INTO messages (id, session_id, role, content, created_at) "
        "VALUES ('cont-legacy', ?, 'assistant', '[上下文已压缩] 旧摘要', ?)",
        (session.id, base + 3),
    )
    conn.execute("UPDATE sessions SET message_count = 2 WHERE id = ?", (session.id,))
    conn.commit()

    restored = restore_compacted_history(db)
    assert restored == 2

    rows = repo.get_by_session(session.id)
    assert len(rows) == 4  # 2 条回填 + 续接 + m2
    assert [r.content for r in rows] == [
        "内容 0",
        "内容 1",
        "[上下文已压缩] 旧摘要",
        "内容 2",
    ]
    # 回填行是展示历史，不进入 LLM 上下文
    assert rows[0].compacted_at is not None
    assert rows[1].compacted_at is not None
    assert [r.content for r in repo.get_active_segment(session.id)] == [
        "[上下文已压缩] 旧摘要",
        "内容 2",
    ]
    assert SessionRepository().get(session.id).message_count == 4

    # 幂等：再次执行不再复制
    assert restore_compacted_history(db) == 0
    assert len(repo.get_by_session(session.id)) == 4
