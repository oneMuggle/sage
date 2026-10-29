"""FeedbackRepo 契约单测（用户反馈系统 Phase 1）。

覆盖会话 CRUD、消息追加/查询/同步标记、附件登记。
"""

from __future__ import annotations

import pytest

from backend.data.database import Database
from backend.data.feedback_repo import FeedbackRepo

pytestmark = pytest.mark.unit


@pytest.fixture()
def repo(tmp_path):
    db = Database(db_path=str(tmp_path / "feedback_test.db"))
    db.init_db()
    try:
        yield FeedbackRepo(db.get_connection())
    finally:
        db.close()


def test_create_conversation_defaults(repo: FeedbackRepo) -> None:
    conv = repo.create_conversation(
        title="导出 PDF 乱码", app_version="0.2.0", os_info="Windows 10"
    )

    assert conv.id
    assert conv.title == "导出 PDF 乱码"
    assert conv.status == "open"
    assert conv.app_version == "0.2.0"
    assert conv.os_info == "Windows 10"
    assert conv.created_at > 0
    assert conv.last_activity_at == conv.created_at


def test_create_conversation_with_explicit_id_is_idempotent(repo: FeedbackRepo) -> None:
    first = repo.create_conversation(id="fixed-uuid", title="标题甲")
    second = repo.create_conversation(id="fixed-uuid", title="标题乙")

    assert first.id == second.id == "fixed-uuid"
    assert repo.get_conversation("fixed-uuid").title == "标题甲"
    assert len(repo.list_conversations()) == 1


def test_get_conversation_missing_returns_none(repo: FeedbackRepo) -> None:
    assert repo.get_conversation("does-not-exist") is None


def test_list_conversations_sorted_by_last_activity(repo: FeedbackRepo) -> None:
    older = repo.create_conversation(title="旧会话")
    newer = repo.create_conversation(title="新会话")
    repo.touch_conversation(newer.id)

    ordered = repo.list_conversations()
    assert ordered[0].id == newer.id
    assert older.id in [c.id for c in ordered]


def test_update_conversation_status(repo: FeedbackRepo) -> None:
    conv = repo.create_conversation(title="待修复")

    assert repo.update_conversation_status(conv.id, "resolved") is True
    assert repo.get_conversation(conv.id).status == "resolved"
    assert repo.update_conversation_status("missing-id", "closed") is False


def test_upsert_remote_ticket(repo: FeedbackRepo) -> None:
    conv = repo.create_conversation(title="带工单号")

    ok = repo.upsert_remote_ticket(
        conv.id, "PROJ-123", "http://jira.local/browse/PROJ-123"
    )
    assert ok is True
    updated = repo.get_conversation(conv.id)
    assert updated.remote_ticket_id == "PROJ-123"
    assert updated.remote_ticket_url == "http://jira.local/browse/PROJ-123"


def test_add_message_bumps_conversation_activity(repo: FeedbackRepo) -> None:
    conv = repo.create_conversation(title="带消息")
    before = repo.get_conversation(conv.id).last_activity_at

    msg = repo.add_message(
        conv.id, role="user", body="导出后中文变乱码", media_ids=["m-1"]
    )

    assert msg.role == "user"
    assert msg.body == "导出后中文变乱码"
    assert msg.media_ids == ["m-1"]
    assert msg.synced_at is None
    assert repo.get_conversation(conv.id).last_activity_at >= before


def test_list_messages_ordered_by_time(repo: FeedbackRepo) -> None:
    conv = repo.create_conversation(title="多消息")
    repo.add_message(conv.id, role="user", body="第一条")
    repo.add_message(conv.id, role="admin", body="第二条")

    messages = repo.list_messages(conv.id)
    assert [m.body for m in messages] == ["第一条", "第二条"]
    assert [m.role for m in messages] == ["user", "admin"]


def test_list_messages_since_filters_older(repo: FeedbackRepo) -> None:
    conv = repo.create_conversation(title="增量拉取")
    first = repo.add_message(conv.id, role="user", body="旧消息")

    assert repo.list_messages(conv.id, since=first.created_at) == []

    repo.add_message(conv.id, role="admin", body="新消息")
    fresh = repo.list_messages(conv.id, since=first.created_at)
    assert [m.body for m in fresh] == ["新消息"]


def test_mark_synced_and_list_unsynced(repo: FeedbackRepo) -> None:
    conv = repo.create_conversation(title="同步标记")
    msg = repo.add_message(conv.id, role="user", body="待同步")

    assert [m.id for m in repo.list_unsynced_messages(conv.id)] == [msg.id]
    assert repo.mark_synced(msg.id) is True
    assert repo.list_unsynced_messages(conv.id) == []
    assert repo.list_messages(conv.id)[0].synced_at is not None


def test_media_ids_survive_json_roundtrip(repo: FeedbackRepo) -> None:
    conv = repo.create_conversation(title="带截图")
    repo.add_message(conv.id, role="user", body="见截图", media_ids=["a", "b"])

    assert repo.list_messages(conv.id)[0].media_ids == ["a", "b"]


def test_get_message_returns_existing_message(repo: FeedbackRepo) -> None:
    conv = repo.create_conversation(title="按 id 查消息")
    msg = repo.add_message(conv.id, role="user", body="hello")

    fetched = repo.get_message(msg.id)
    assert fetched is not None
    assert fetched.id == msg.id
    assert fetched.body == "hello"


def test_get_message_missing_returns_none(repo: FeedbackRepo) -> None:
    assert repo.get_message("does-not-exist") is None


def test_add_message_explicit_id_is_idempotent(repo: FeedbackRepo) -> None:
    conv = repo.create_conversation(title="幂等写入")
    first = repo.add_message(
        conv.id, role="admin", body="管理员回复", id="admin-msg-1"
    )
    second = repo.add_message(
        conv.id, role="admin", body="管理员回复", id="admin-msg-1"
    )

    assert first.id == second.id == "admin-msg-1"
    messages = repo.list_messages(conv.id)
    assert len(messages) == 1
    assert messages[0].body == "管理员回复"


def test_add_message_distinct_ids_coexist(repo: FeedbackRepo) -> None:
    conv = repo.create_conversation(title="不同 id")
    repo.add_message(conv.id, role="admin", body="第一条", id="msg-a")
    repo.add_message(conv.id, role="admin", body="第二条", id="msg-b")

    assert len(repo.list_messages(conv.id)) == 2


def test_add_and_list_attachments(repo: FeedbackRepo) -> None:
    conv = repo.create_conversation(title="附件")

    repo.add_attachment(
        conv.id,
        filename="shot.png",
        mime_type="image/png",
        size_bytes=1234,
        id="att-1",
    )
    attachments = repo.list_attachments(conv.id)
    assert len(attachments) == 1
    assert attachments[0].filename == "shot.png"
    assert attachments[0].size_bytes == 1234


def test_delete_conversation_cascades_messages(repo: FeedbackRepo) -> None:
    conv = repo.create_conversation(title="待删")
    repo.add_message(conv.id, role="user", body="消息")

    repo._conn.execute("DELETE FROM feedback_conversations WHERE id = ?", (conv.id,))
    repo._conn.commit()

    assert repo.list_messages(conv.id) == []
