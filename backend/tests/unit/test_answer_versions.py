# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""C2 (对话阅读体验第二轮): 回答版本仓储 —— 归档 / 列出 / 切换，以及 producer 接线辅助。

关注点: 事件日志投影（模型可见历史）与 messages 表同步、message_count、恢复用新 id、
只对最后一轮生效。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.chat.event_projection import events_to_history
from backend.data.answer_version_repo import (
    CURRENT_VERSION_ID,
    AnswerVersionError,
    AnswerVersionRepository,
    ArchiveOnFirstSave,
    drop_excluded,
    regenerate_excluded_ids,
)
from backend.data.database import get_database
from backend.data.session_event_repo import SessionEventRepository
from backend.data.session_repo import Message, MessageRepository, SessionRepository

pytestmark = pytest.mark.unit


def _session_with_turn(answer: str = "旧回答", **answer_fields):
    session = SessionRepository().create(title="c2")
    repo = MessageRepository()
    repo.save(Message(id="u1", session_id=session.id, role="user", content="问", created_at=1))
    repo.save(
        Message(
            id="a1",
            session_id=session.id,
            role="assistant",
            content=answer,
            created_at=2,
            **answer_fields,
        )
    )
    SessionRepository().update(session.id, message_count=2)
    return session.id


def _rows(session_id: str):
    return [(m.id, m.role, m.content) for m in MessageRepository().get_by_session(session_id)]


def _history(session_id: str):
    return events_to_history(SessionEventRepository().get_by_session(session_id))


def _version_count(session_id: str) -> int:
    conn = get_database().get_connection()
    row = conn.execute(
        "SELECT COUNT(*) FROM message_versions WHERE session_id = ?", (session_id,)
    ).fetchone()
    return int(row[0])


def test_archive_turn_moves_the_answer_into_a_version():
    sid = _session_with_turn()

    assert AnswerVersionRepository().archive_turn(sid, "u1") == 1

    assert _rows(sid) == [("u1", "user", "问")]
    assert _version_count(sid) == 1
    assert SessionRepository().get(sid).message_count == 1
    # 模型可见历史同步排除旧回答
    assert _history(sid) == [{"role": "user", "content": "问"}]


def test_archive_turn_requires_the_last_turn():
    sid = _session_with_turn()
    MessageRepository().save(
        Message(id="u2", session_id=sid, role="user", content="追问", created_at=3)
    )
    repo = AnswerVersionRepository()

    with pytest.raises(AnswerVersionError) as not_last:
        repo.archive_turn(sid, "u1")
    assert not_last.value.kind == "anchor_not_last"
    with pytest.raises(AnswerVersionError) as missing:
        repo.archive_turn(sid, "nope")
    assert missing.value.kind == "anchor_not_found"
    assert repo.is_last_turn(sid, "u2") is True
    assert repo.is_last_turn(sid, "u1") is False


def test_archive_turn_without_an_answer_is_a_noop():
    session = SessionRepository().create(title="c2-empty")
    MessageRepository().save(
        Message(id="u1", session_id=session.id, role="user", content="问", created_at=1)
    )

    assert AnswerVersionRepository().archive_turn(session.id, "u1") == 0
    assert _version_count(session.id) == 0


def test_list_versions_orders_versions_and_marks_the_current_one():
    sid = _session_with_turn()
    repo = AnswerVersionRepository()
    repo.archive_turn(sid, "u1")
    MessageRepository().save(
        Message(id="a2", session_id=sid, role="assistant", content="新回答", created_at=3)
    )

    listing = repo.list_versions(sid)

    assert listing["anchor_id"] == "u1"
    assert listing["total"] == 2
    assert listing["current_index"] == 2
    assert [v["preview"] for v in listing["versions"]] == ["旧回答", "新回答"]
    assert listing["versions"][1]["id"] == CURRENT_VERSION_ID
    assert listing["versions"][0]["current"] is False


def test_list_versions_without_a_switchable_turn():
    session = SessionRepository().create(title="c2-none")
    assert AnswerVersionRepository().list_versions(session.id) == {
        "anchor_id": None,
        "total": 0,
        "current_index": 0,
        "versions": [],
    }


def test_activate_restores_the_version_with_new_ids():
    stats = json.dumps({"output_tokens": 12})
    sid = _session_with_turn(generation_stats=stats)
    repo = AnswerVersionRepository()
    repo.archive_turn(sid, "u1")
    MessageRepository().save(
        Message(id="a2", session_id=sid, role="assistant", content="新回答", created_at=3)
    )
    SessionRepository().update(sid, message_count=2)
    version_id = repo.list_versions(sid)["versions"][0]["id"]

    assert repo.activate(sid, version_id) == 1

    messages = MessageRepository().get_by_session(sid)
    assert [(m.role, m.content) for m in messages] == [("user", "问"), ("assistant", "旧回答")]
    restored = messages[1]
    assert restored.id not in {"a1", "a2"}
    assert restored.generation_stats == stats
    # 被替换的新回答成了版本, 目标版本出列; 计数不变
    listing = repo.list_versions(sid)
    assert listing["total"] == 2
    assert listing["current_index"] == 1
    assert SessionRepository().get(sid).message_count == 2
    # 事件日志: 恢复的行以新 id 追加, 模型历史与表一致
    assert _history(sid) == [
        {"role": "user", "content": "问"},
        {"role": "assistant", "content": "旧回答"},
    ]


def test_activate_rejects_unknown_versions():
    sid = _session_with_turn()
    other = SessionRepository().create(title="c2-other").id
    messages = MessageRepository()
    messages.save(Message(id="ou1", session_id=other, role="user", content="别的", created_at=1))
    messages.save(
        Message(id="oa1", session_id=other, role="assistant", content="别的回答", created_at=2)
    )
    repo = AnswerVersionRepository()
    repo.archive_turn(other, "ou1")
    foreign_id = repo.list_versions(other)["versions"][0]["id"]

    for version_id in ("ver-missing", foreign_id):
        with pytest.raises(AnswerVersionError) as err:
            repo.activate(sid, version_id)
        assert err.value.kind == "version_not_found"


def test_regenerate_helpers_exclude_the_anchor_and_old_answer():
    sid = _session_with_turn()

    excluded = regenerate_excluded_ids(sid, "u1")

    assert excluded == {"u1", "a1"}
    assert regenerate_excluded_ids(sid, None) == set()
    rows = [SimpleNamespace(id="u0"), SimpleNamespace(id="u1"), SimpleNamespace(id="a1")]
    assert [r.id for r in drop_excluded(rows, excluded)] == ["u0"]
    events = [
        SimpleNamespace(id=1, payload={"id": "u1"}),
        SimpleNamespace(id=2, payload={"deleted_ids": ["x"]}),
    ]
    assert [e.id for e in drop_excluded(events, excluded)] == [2]
    assert drop_excluded(rows, set()) is rows


def test_archive_on_first_save_replaces_the_old_answer_once():
    sid = _session_with_turn()
    repo = ArchiveOnFirstSave(MessageRepository(), sid, "u1")

    repo.save(Message(id="a2", session_id=sid, role="assistant", content="第一步", created_at=3))
    repo.save(Message(id="a3", session_id=sid, role="assistant", content="终稿", created_at=4))

    assert _rows(sid) == [
        ("u1", "user", "问"),
        ("a2", "assistant", "第一步"),
        ("a3", "assistant", "终稿"),
    ]
    assert _version_count(sid) == 1
    # 其余方法透传给被包装的仓储
    assert repo.get("a3").content == "终稿"
