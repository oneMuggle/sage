"""R184 — 回答版本仓储单元测试（`backend/data/answer_version_repo.py`）。

真实临时库（conftest autouse `setup_test_db`）+ SessionRepository /
MessageRepository 造真实数据。覆盖最后一轮归档 / 切换恢复 / 事件双写 /
producer 接线（excluded ids、drop_excluded、ArchiveOnFirstSave）。
"""

from __future__ import annotations

import pytest

from backend.data.answer_version_repo import (
    CURRENT_VERSION_ID,
    AnswerVersionError,
    AnswerVersionRepository,
    ArchiveOnFirstSave,
    _preview,
    drop_excluded,
    regenerate_excluded_ids,
)
from backend.data.session_event_repo import SessionEventRepository
from backend.data.session_repo import Message, MessageRepository, SessionRepository

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 数据构造
# ---------------------------------------------------------------------------


@pytest.fixture()
def session() -> str:
    return SessionRepository().create(title="版本会话").id


def _msg(sid: str, mid: str, role: str, content: str, ts: int) -> Message:
    return Message(id=mid, session_id=sid, role=role, content=content, created_at=ts)


def _seed_turn(sid: str, answer: str = "回答 v1", base: int = 1000) -> str:
    """落一个 user 锚点 + 一条 assistant 回答，返回锚点 id。"""
    repo = MessageRepository()
    repo.save(_msg(sid, "anchor-1", "user", "问题", base))
    repo.save(_msg(sid, "ans-1", "assistant", answer, base + 1))
    return "anchor-1"


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------


def test_last_user_message_id(session: str) -> None:
    repo = AnswerVersionRepository()
    assert repo.last_user_message_id(session) is None
    _seed_turn(session)
    assert repo.last_user_message_id(session) == "anchor-1"
    MessageRepository().save(_msg(session, "anchor-2", "user", "追问", 2000))
    assert repo.last_user_message_id(session) == "anchor-2"


def test_turn_message_ids(session: str) -> None:
    repo = AnswerVersionRepository()
    MessageRepository().save(_msg(session, "a0", "assistant", "开场白", 900))
    anchor = _seed_turn(session)
    assert repo.turn_message_ids(session, anchor) == ["ans-1"]


def test_turn_message_ids_anchor_missing(session: str) -> None:
    _seed_turn(session)
    assert AnswerVersionRepository().turn_message_ids(session, "ghost") == []


def test_turn_message_ids_anchor_not_last(session: str) -> None:
    repo = MessageRepository()
    repo.save(_msg(session, "anchor-1", "user", "第一问", 1000))
    repo.save(_msg(session, "ans-1", "assistant", "第一答", 1001))
    repo.save(_msg(session, "anchor-2", "user", "第二问", 1002))
    # 锚点后还有别的 user 消息 → 非最后一轮
    assert AnswerVersionRepository().turn_message_ids(session, "anchor-1") == []
    assert AnswerVersionRepository().is_last_turn(session, "anchor-1") is False
    assert AnswerVersionRepository().is_last_turn(session, "anchor-2") is True


def test_list_versions_empty(session: str) -> None:
    out = AnswerVersionRepository().list_versions(session)
    assert out == {"anchor_id": None, "total": 0, "current_index": 0, "versions": []}


def test_list_versions_sorted_with_current(session: str) -> None:
    repo = AnswerVersionRepository()
    anchor = _seed_turn(session, answer="第一版回答")
    repo.archive_turn(session, anchor)
    MessageRepository().save(_msg(session, "ans-2", "assistant", "第二版回答", 2000))

    out = repo.list_versions(session)
    assert out["anchor_id"] == anchor
    assert out["total"] == 2
    previews = [v["preview"] for v in out["versions"]]
    assert previews == ["第一版回答", "第二版回答"]  # generated_at 升序
    assert out["versions"][1]["id"] == CURRENT_VERSION_ID
    assert out["current_index"] == 2


# ---------------------------------------------------------------------------
# archive_turn
# ---------------------------------------------------------------------------


def test_archive_turn_moves_rows_and_bumps_count(session: str) -> None:
    answer_repo = AnswerVersionRepository()
    anchor = _seed_turn(session, answer="旧回答")
    assert answer_repo.archive_turn(session, anchor) == 1

    # 消息行删除 + 版本行写入
    assert MessageRepository().get("ans-1") is None
    versions = answer_repo.list_versions(session)
    assert versions["total"] == 1
    assert versions["versions"][0]["preview"] == "旧回答"

    # session.message_count 回减（repo.save 不维护计数，从 0 起 → MAX(0,…) 钳到 0）
    row = (
        AnswerVersionRepository()
        .db.get_connection()
        .cursor()
        .execute("SELECT message_count FROM sessions WHERE id = ?", (session,))
        .fetchone()
    )
    assert row["message_count"] == 0

    # 事件双写 message.deleted
    events = SessionEventRepository().get_by_session(session)
    deleted = [e for e in events if e.type == "message.deleted"]
    assert any(getattr(e, "payload", {}).get("id") == "ans-1" for e in deleted)


def test_archive_turn_without_answer_returns_zero(session: str) -> None:
    repo = MessageRepository()
    repo.save(_msg(session, "anchor-1", "user", "问题", 1000))
    assert AnswerVersionRepository().archive_turn(session, "anchor-1") == 0


def test_archive_turn_anchor_not_found_raises(session: str) -> None:
    _seed_turn(session)
    with pytest.raises(AnswerVersionError) as ei:
        AnswerVersionRepository().archive_turn(session, "ghost")
    assert ei.value.kind == "anchor_not_found"


def test_archive_turn_anchor_not_last_raises(session: str) -> None:
    repo = MessageRepository()
    repo.save(_msg(session, "anchor-1", "user", "一问", 1000))
    repo.save(_msg(session, "ans-1", "assistant", "一答", 1001))
    repo.save(_msg(session, "anchor-2", "user", "二问", 1002))
    with pytest.raises(AnswerVersionError) as ei:
        AnswerVersionRepository().archive_turn(session, "anchor-1")
    assert ei.value.kind == "anchor_not_last"


# ---------------------------------------------------------------------------
# activate
# ---------------------------------------------------------------------------


def test_activate_restores_with_new_ids(session: str) -> None:
    answer_repo = AnswerVersionRepository()
    anchor = _seed_turn(session, answer="第一版")
    answer_repo.archive_turn(session, anchor)
    versions = answer_repo.list_versions(session)
    v1_id = versions["versions"][0]["id"]

    # 重新生成出第二版（当前显示）
    MessageRepository().save(_msg(session, "ans-2", "assistant", "第二版", 2000))
    answer_repo.archive_turn(session, anchor)
    MessageRepository().save(_msg(session, "ans-3", "assistant", "第三版", 3000))

    restored = answer_repo.activate(session, v1_id)
    assert restored == 1

    # 第一版以新 id 回到当前（generated_at 1001 排最前）；
    # 第二版、第三版各占一个归档版本
    rows = answer_repo.list_versions(session)
    assert rows["total"] == 3
    assert rows["current_index"] == 1
    current_entry = rows["versions"][0]
    assert current_entry["id"] == CURRENT_VERSION_ID
    assert current_entry["current"] is True
    assert current_entry["preview"] == "第一版"

    ids = answer_repo.turn_message_ids(session, anchor)
    assert ids  # 本轮有恢复的消息行
    assert ids[0] != "ans-1"  # id 必须换新（日志里 id 不复用）
    assert MessageRepository().get(ids[0]).content == "第一版"

    # 消费掉的版本行已删除
    assert all(v["id"] != v1_id for v in rows["versions"])


def test_activate_version_not_found(session: str) -> None:
    _seed_turn(session)
    with pytest.raises(AnswerVersionError) as ei:
        AnswerVersionRepository().activate(session, "ver-ghost")
    assert ei.value.kind == "version_not_found"


# ---------------------------------------------------------------------------
# producer 接线
# ---------------------------------------------------------------------------


def test_regenerate_excluded_ids(session: str) -> None:
    assert regenerate_excluded_ids(session, None) == set()
    anchor = _seed_turn(session, answer="旧回答")
    assert regenerate_excluded_ids(session, anchor) == {"anchor-1", "ans-1"}


def test_regenerate_excluded_ids_query_failure_still_excludes_anchor(
    monkeypatch: pytest.MonkeyPatch, session: str
) -> None:
    anchor = _seed_turn(session)
    monkeypatch.setattr(
        AnswerVersionRepository,
        "turn_message_ids",
        lambda self, sid, aid: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert regenerate_excluded_ids(session, anchor) == {"anchor-1"}


class _Row:
    def __init__(self, id: str) -> None:
        self.id = id


class _Event:
    def __init__(self, payload: dict) -> None:
        self.payload = payload


def test_drop_excluded_rows_and_events() -> None:
    items = [_Row("a"), _Row("b"), _Event({"id": "a"}), _Event({"id": "c"})]
    out = drop_excluded(items, {"a"})
    assert [i.id for i in out if isinstance(i, _Row)] == ["b"]
    assert [e.payload["id"] for e in out if isinstance(e, _Event)] == ["c"]
    assert drop_excluded(items, set()) is items


def test_preview_truncates_and_takes_last_assistant() -> None:
    rows = [
        {"role": "user", "content": "x" * 200},
        {"role": "assistant", "content": "  多  空白\n文本  "},
        {"role": "assistant", "content": "y" * 120},
        {"role": "tool", "content": "ignored"},
    ]
    out = _preview(rows)
    assert out == "y" * 80
    assert _preview([{"role": "assistant", "content": "   "}]) == ""
    assert _preview([]) == ""


# ---------------------------------------------------------------------------
# ArchiveOnFirstSave
# ---------------------------------------------------------------------------


def test_archive_on_first_save_archives_once(session: str) -> None:
    repo = MessageRepository()
    anchor = _seed_turn(session, answer="旧回答")

    calls: list[str] = []
    real_archive = AnswerVersionRepository.archive_turn

    def _spy(self, sid: str, aid: str) -> int:
        calls.append(aid)
        return real_archive(self, sid, aid)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(AnswerVersionRepository, "archive_turn", _spy)
    try:
        wrapper = ArchiveOnFirstSave(repo, session, anchor)
        wrapper.save(_msg(session, "new-1", "assistant", "新回答", 3000))
        wrapper.save(_msg(session, "new-2", "assistant", "新回答续", 3001))
    finally:
        monkeypatch.undo()

    assert calls == [anchor]  # 只在本轮第一次落库前归档一次
    assert MessageRepository().get("new-1") is not None
    assert MessageRepository().get("new-2") is not None


def test_archive_on_first_save_failure_does_not_block(session: str, monkeypatch) -> None:
    repo = MessageRepository()
    anchor = _seed_turn(session)

    def _boom(self, sid: str, aid: str) -> int:
        raise RuntimeError("archive failed")

    monkeypatch.setattr(AnswerVersionRepository, "archive_turn", _boom)
    wrapper = ArchiveOnFirstSave(repo, session, anchor)
    saved = wrapper.save(_msg(session, "new-1", "assistant", "新回答", 3000))
    assert saved.id == "new-1"  # 归档失败不阻断新回答落库
    # 旧回答原样保留
    assert MessageRepository().get("ans-1") is not None


def test_archive_on_first_save_delegates_attrs(session: str) -> None:
    repo = MessageRepository()
    wrapper = ArchiveOnFirstSave(repo, session, "anchor-1")
    assert wrapper.get("ghost") is None  # __getattr__ 透传 repo 方法
