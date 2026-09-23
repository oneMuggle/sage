# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""存量会话事件回填测试（DSH 对标 R2，SE2）。

覆盖：legacy 行（绕过双写钩子、直接 SQL 插入）→ backfill → 投影
parity；幂等（二次运行零写入）；有事件的会话整体跳过；跨会话隔离。
"""

from __future__ import annotations

import time

import pytest

from backend.chat.event_projection import events_to_history
from backend.chat.history_context import db_rows_to_history
from backend.data.session_event_backfill import backfill_session_events
from backend.data.session_event_repo import SessionEventRepository
from backend.data.session_repo import MessageRepository
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit


def _raw_insert_legacy_message(db, sid, idx, role, content, created_at, **cols):
    """绕过 MessageRepository.save 的双写钩子，模拟 SE1 之前的存量行。"""
    db.get_connection().execute(
        "INSERT INTO messages (id, session_id, role, content, created_at, segment_id, subtype) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            f"legacy-{sid}-{idx:03d}",
            sid,
            role,
            content,
            created_at,
            cols.get("segment_id", 0),
            cols.get("subtype"),
        ),
    )


def test_backfill_legacy_rows_and_parity(setup_test_db):
    sid = "s-backfill-1"
    ensure_session(setup_test_db, sid)
    now = int(time.time() * 1000)

    # 存量行：白名单内外角色混合 + 空内容（投影语义与表投影一致即可）
    _raw_insert_legacy_message(setup_test_db, sid, 1, "user", "旧问一", now + 1)
    _raw_insert_legacy_message(setup_test_db, sid, 2, "assistant", "旧答一", now + 2)
    _raw_insert_legacy_message(setup_test_db, sid, 3, "tool", "工具结果", now + 3)
    _raw_insert_legacy_message(setup_test_db, sid, 4, "assistant", "   ", now + 4)
    _raw_insert_legacy_message(setup_test_db, sid, 5, "user", "旧问二", now + 5)
    setup_test_db.get_connection().commit()

    result = backfill_session_events(setup_test_db)
    assert result["sessions_backfilled"] == 1
    assert result["events_written"] == 5

    # parity：回填后的投影与表投影逐字节一致
    messages = MessageRepository().get_by_session(sid, limit=100000)
    events = SessionEventRepository().get_by_session(sid)
    assert events_to_history(events) == db_rows_to_history(messages)

    # 事件 seq 按 created_at 保序
    assert [e.seq for e in events] == [1, 2, 3, 4, 5]


def test_backfill_is_idempotent(setup_test_db):
    sid = "s-backfill-2"
    ensure_session(setup_test_db, sid)
    now = int(time.time() * 1000)
    _raw_insert_legacy_message(setup_test_db, sid, 1, "user", "问", now + 1)
    setup_test_db.get_connection().commit()

    first = backfill_session_events(setup_test_db)
    assert first["events_written"] == 1

    # 第二次运行：会话已有事件 → 整体跳过，零写入
    second = backfill_session_events(setup_test_db)
    assert second["events_written"] == 0
    assert second["sessions_backfilled"] == 0
    assert SessionEventRepository().count_by_session(sid) == 1


def test_backfill_skips_sessions_with_events(setup_test_db):
    """SE1 双写路径写过的会话（已有事件）绝不被 backfill 重复补写。"""
    from backend.data.session_repo import Message

    sid = "s-backfill-3"
    ensure_session(setup_test_db, sid)
    now = int(time.time() * 1000)

    # 双写路径写入（save() 落消息 + 事件）
    MessageRepository().save(
        Message(
            id="dual-1",
            session_id=sid,
            role="user",
            content="双写消息",
            created_at=now + 1,
        )
    )
    assert SessionEventRepository().count_by_session(sid) == 1

    result = backfill_session_events(setup_test_db)
    assert result["sessions_backfilled"] == 0
    assert SessionEventRepository().count_by_session(sid) == 1


def test_backfill_multiple_sessions_isolated(setup_test_db):
    ensure_session(setup_test_db, "s-bf-a")
    ensure_session(setup_test_db, "s-bf-b")
    now = int(time.time() * 1000)
    _raw_insert_legacy_message(setup_test_db, "s-bf-a", 1, "user", "A问", now + 1)
    _raw_insert_legacy_message(setup_test_db, "s-bf-b", 1, "user", "B问", now + 1)
    _raw_insert_legacy_message(setup_test_db, "s-bf-b", 2, "assistant", "B答", now + 2)
    setup_test_db.get_connection().commit()

    result = backfill_session_events(setup_test_db)
    assert result["sessions_backfilled"] == 2
    assert result["events_written"] == 3

    repo = SessionEventRepository()
    assert repo.count_by_session("s-bf-a") == 1
    assert repo.count_by_session("s-bf-b") == 2
    # 事件互不串味
    assert repo.get_by_session("s-bf-a")[0].payload["content"] == "A问"
