# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""SessionEventRepository 单元测试（DSH 对标 R1，SE1）。

覆盖：seq 单调分配、payload/surface_op JSON 往返、读取排序、
append-only 契约（无删除入口）、跨会话隔离、同事务追加可见性。
"""

from __future__ import annotations

import pytest

from backend.data.session_event_repo import (
    EVENT_COMPACTION_PERFORMED,
    EVENT_MESSAGE_APPENDED,
    SessionEventRepository,
)
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit


@pytest.fixture()
def repo():
    return SessionEventRepository()


# ---- seq 分配与读取 ----


def test_append_assigns_monotonic_seq(setup_test_db, repo):
    ensure_session(setup_test_db, "s1")
    assert repo.append("s1", EVENT_MESSAGE_APPENDED, payload={"role": "user"}) == 1
    assert repo.append("s1", EVENT_MESSAGE_APPENDED, payload={"role": "assistant"}) == 2
    assert repo.latest_seq("s1") == 2

    events = repo.get_by_session("s1")
    assert [e.seq for e in events] == [1, 2]
    assert all(e.type == EVENT_MESSAGE_APPENDED for e in events)


def test_payload_and_surface_op_roundtrip(setup_test_db, repo):
    ensure_session(setup_test_db, "s1")
    payload = {"role": "user", "content": "你好", "tool_calls": None}
    surface = {"op": "replace", "start_seq": 1, "end_seq": 3}
    repo.append(
        "s1",
        EVENT_COMPACTION_PERFORMED,
        payload=payload,
        surface_op=surface,
        created_at=1234567890,
    )

    event = repo.get_by_session("s1")[0]
    assert event.payload == payload
    assert event.surface_op == surface
    assert event.created_at == 1234567890


def test_broken_payload_json_degrades_to_none(setup_test_db):
    ensure_session(setup_test_db, "s1")
    conn = setup_test_db.get_connection()
    conn.execute(
        "INSERT INTO session_events (session_id, seq, type, payload, created_at) "
        "VALUES ('s1', 1, 'message.appended', '{not-json', 1)"
    )
    conn.commit()

    repo = SessionEventRepository()
    event = repo.get_by_session("s1")[0]
    assert event.payload is None


def test_sessions_are_isolated(setup_test_db, repo):
    ensure_session(setup_test_db, "s1")
    ensure_session(setup_test_db, "s2")
    repo.append("s1", EVENT_MESSAGE_APPENDED)
    repo.append("s2", EVENT_MESSAGE_APPENDED)
    repo.append("s2", EVENT_MESSAGE_APPENDED)

    assert repo.count_by_session("s1") == 1
    assert repo.count_by_session("s2") == 2
    # 每个会话各自从 1 开始单调
    assert [e.seq for e in repo.get_by_session("s1")] == [1]
    assert [e.seq for e in repo.get_by_session("s2")] == [1, 2]
    assert repo.latest_seq("s2") == 2


def test_no_events_returns_empty_and_zero(setup_test_db, repo):
    ensure_session(setup_test_db, "s-empty")
    assert repo.get_by_session("s-empty") == []
    assert repo.count_by_session("s-empty") == 0
    assert repo.latest_seq("s-empty") == 0


def test_append_with_cursor_shares_transaction(setup_test_db, repo):
    """append_with_cursor 必须跟随调用方事务：调用方回滚则事件一并消失。"""
    ensure_session(setup_test_db, "s1")
    conn = setup_test_db.get_connection()
    cursor = conn.cursor()
    SessionEventRepository.append_with_cursor(
        cursor, "s1", EVENT_MESSAGE_APPENDED, payload={"role": "user"}
    )
    conn.rollback()
    # 随调用方事务回滚 —— 事件未被独立提交
    assert repo.count_by_session("s1") == 0

    # 再追加并 commit —— 可见
    cursor = conn.cursor()
    SessionEventRepository.append_with_cursor(
        cursor, "s1", EVENT_MESSAGE_APPENDED, payload={"role": "user"}
    )
    conn.commit()
    assert repo.count_by_session("s1") == 1


def test_append_only_no_delete_entry(repo):
    """append-only 契约：仓储不暴露任何删除/更新入口。"""
    for banned in ("delete", "update", "upsert", "truncate"):
        assert not hasattr(repo, banned), f"SessionEventRepository 不应有 {banned}"


def test_to_dict_roundtrip(setup_test_db, repo):
    ensure_session(setup_test_db, "s1")
    repo.append("s1", EVENT_MESSAGE_APPENDED, payload={"role": "user"})
    d = repo.get_by_session("s1")[0].to_dict()
    assert d["type"] == EVENT_MESSAGE_APPENDED
    assert d["payload"] == {"role": "user"}
    assert set(d.keys()) == {
        "id",
        "session_id",
        "seq",
        "type",
        "payload",
        "surface_op",
        "created_at",
    }
