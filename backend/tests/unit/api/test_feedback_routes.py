"""用户反馈路由单元测试（Phase 1）。

直接调用路由函数，数据库与 MediaStore 根目录打桩到 tmp 目录。
覆盖：创建会话(校验/幂等)、列表、详情 404、追消息(角色/空内容校验)、
状态更新、附件上传(空/超限)、日志尾部。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.api import feedback_routes as fr

pytestmark = pytest.mark.unit

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture()
def routed(tmp_path, monkeypatch):
    """把 feedback_routes 绑到临时数据库 + 临时媒体目录。"""
    from backend.data.database import Database

    db = Database(db_path=str(tmp_path / "feedback_routes_test.db"))
    db.init_db()
    monkeypatch.setattr(fr, "get_database", lambda: db)
    monkeypatch.setattr(fr, "MEDIA_ROOT", tmp_path / "media")
    try:
        yield db
    finally:
        db.close()


class _FakeRequest:
    """最小 Request 替身：提供 headers 与异步 body()。"""

    def __init__(self, body: bytes, headers=None):
        self._body = body
        self.headers = headers or {}

    async def body(self) -> bytes:
        return self._body


def test_create_conversation_with_first_message(routed) -> None:
    dto = fr.create_conversation(
        fr.CreateConversationRequest(title="导出 PDF 乱码", body="见截图")
    )

    assert dto.id
    assert dto.title == "导出 PDF 乱码"
    assert dto.status == "open"
    assert dto.app_version
    assert dto.os_info

    detail = fr.get_conversation(dto.id)
    assert [m.body for m in detail.messages] == ["见截图"]
    assert detail.messages[0].role == "user"


def test_create_conversation_rejects_blank_title(routed) -> None:
    with pytest.raises(HTTPException) as ei:
        fr.create_conversation(fr.CreateConversationRequest(title="   "))
    assert ei.value.status_code == 422


def test_create_conversation_rejects_overlong_title(routed) -> None:
    with pytest.raises(HTTPException) as ei:
        fr.create_conversation(
            fr.CreateConversationRequest(title="x" * (fr.MAX_TITLE_CHARS + 1))
        )
    assert ei.value.status_code == 422


def test_create_conversation_with_same_id_is_idempotent(routed) -> None:
    fr.create_conversation(fr.CreateConversationRequest(id="cid-1", title="甲"))
    second = fr.create_conversation(fr.CreateConversationRequest(id="cid-1", title="乙"))

    assert second.id == "cid-1"
    assert len(fr.list_conversations()) == 1


def test_list_conversations_returns_created(routed) -> None:
    fr.create_conversation(fr.CreateConversationRequest(title="会话一"))

    items = fr.list_conversations()
    assert len(items) == 1
    assert items[0].title == "会话一"


def test_get_conversation_missing_404(routed) -> None:
    with pytest.raises(HTTPException) as ei:
        fr.get_conversation("missing")
    assert ei.value.status_code == 404


def test_append_message_accepted(routed) -> None:
    conv = fr.create_conversation(fr.CreateConversationRequest(title="会话"))

    resp = fr.append_message(
        conv.id,
        fr.AppendMessageRequest(role="admin", body="已复现，下周修复"),
    )

    assert resp.received is True
    detail = fr.get_conversation(conv.id)
    assert detail.messages[-1].role == "admin"
    assert detail.messages[-1].body == "已复现，下周修复"


def test_append_message_rejects_invalid_role(routed) -> None:
    conv = fr.create_conversation(fr.CreateConversationRequest(title="会话"))

    with pytest.raises(HTTPException) as ei:
        fr.append_message(conv.id, fr.AppendMessageRequest(role="system", body="x"))
    assert ei.value.status_code == 422


def test_append_message_rejects_empty_body(routed) -> None:
    conv = fr.create_conversation(fr.CreateConversationRequest(title="会话"))

    with pytest.raises(HTTPException) as ei:
        fr.append_message(conv.id, fr.AppendMessageRequest(body="   "))
    assert ei.value.status_code == 422


def test_append_message_to_missing_conversation_404(routed) -> None:
    with pytest.raises(HTTPException) as ei:
        fr.append_message("missing", fr.AppendMessageRequest(body="hi"))
    assert ei.value.status_code == 404


def test_update_status_rejects_invalid_value(routed) -> None:
    conv = fr.create_conversation(fr.CreateConversationRequest(title="会话"))

    with pytest.raises(HTTPException) as ei:
        fr.update_status(conv.id, fr.UpdateStatusRequest(status="archived"))
    assert ei.value.status_code == 422


def test_update_status_accepts_valid_value(routed) -> None:
    conv = fr.create_conversation(fr.CreateConversationRequest(title="会话"))

    dto = fr.update_status(conv.id, fr.UpdateStatusRequest(status="resolved"))
    assert dto.status == "resolved"


@pytest.mark.asyncio()
async def test_upload_attachment_stores_media(routed) -> None:
    conv = fr.create_conversation(fr.CreateConversationRequest(title="会话"))

    dto = await fr.upload_attachment(
        conv.id,
        _FakeRequest(PNG_BYTES, {"content-type": "image/png", "x-filename": "shot.png"}),
    )

    assert dto.conversation_id == conv.id
    assert dto.filename == "shot.png"
    assert dto.size_bytes == len(PNG_BYTES)
    assert dto.mime_type == "image/png"


@pytest.mark.asyncio()
async def test_upload_attachment_rejects_empty_body(routed) -> None:
    conv = fr.create_conversation(fr.CreateConversationRequest(title="会话"))

    with pytest.raises(HTTPException) as ei:
        await fr.upload_attachment(conv.id, _FakeRequest(b""))
    assert ei.value.status_code == 422


@pytest.mark.asyncio()
async def test_upload_attachment_rejects_oversize_body(routed) -> None:
    conv = fr.create_conversation(fr.CreateConversationRequest(title="会话"))
    oversized = b"0" * (fr.MAX_ATTACHMENT_BYTES + 1)

    with pytest.raises(HTTPException) as ei:
        await fr.upload_attachment(conv.id, _FakeRequest(oversized))
    assert ei.value.status_code == 413


def test_log_tail_returns_lines(routed, monkeypatch) -> None:
    monkeypatch.setattr(fr, "collect_log_tail", lambda max_lines=200: "line1\nline2")

    resp = fr.get_log_tail()
    assert resp.text == "line1\nline2"
    assert resp.lines == ["line1", "line2"]


def test_list_pending_messages_returns_unsynced_only(routed) -> None:
    conv = fr.create_conversation(fr.CreateConversationRequest(title="待转发"))

    fr.append_message(conv.id, fr.AppendMessageRequest(body="第一条"))
    fr.append_message(conv.id, fr.AppendMessageRequest(body="第二条"))

    pending = fr.list_pending_messages(conv.id)
    assert [m.body for m in pending] == ["第一条", "第二条"]
    assert all(m.synced_at is None for m in pending)

    # 标记第一条为已同步,只剩第二条在 outbox
    fr.mark_message_synced(pending[0].id)
    remaining = fr.list_pending_messages(conv.id)
    assert [m.body for m in remaining] == ["第二条"]


def test_list_pending_messages_missing_conversation_404(routed) -> None:
    with pytest.raises(HTTPException) as ei:
        fr.list_pending_messages("missing")
    assert ei.value.status_code == 404


def test_mark_message_synced_sets_timestamp(routed) -> None:
    conv = fr.create_conversation(fr.CreateConversationRequest(title="同步标记"))
    msg = fr.append_message(conv.id, fr.AppendMessageRequest(body="待同步"))

    resp = fr.mark_message_synced(msg.id)
    assert resp.id == msg.id
    assert resp.synced_at > 0

    detail = fr.get_conversation(conv.id)
    assert detail.messages[-1].synced_at == resp.synced_at


def test_mark_message_synced_missing_404(routed) -> None:
    with pytest.raises(HTTPException) as ei:
        fr.mark_message_synced("ghost-message")
    assert ei.value.status_code == 404


def test_search_returns_matches(routed) -> None:
    conv = fr.create_conversation(
        fr.CreateConversationRequest(title="导出 PDF 乱码", body="导出后中文变乱码")
    )

    hits = fr.search_messages(q="乱码")

    assert len(hits) == 1
    assert hits[0].conversation_id == conv.id
    assert hits[0].conversation_title == "导出 PDF 乱码"
    assert hits[0].body == "导出后中文变乱码"
    assert hits[0].created_at > 0


def test_search_blank_query_returns_empty(routed) -> None:
    fr.create_conversation(fr.CreateConversationRequest(title="会话", body="内容"))

    assert fr.search_messages(q="") == []
    assert fr.search_messages(q="   ") == []


def test_search_no_match_returns_empty(routed) -> None:
    fr.create_conversation(fr.CreateConversationRequest(title="会话", body="无关内容"))

    assert fr.search_messages(q="乱码") == []


def test_search_rejects_overlong_query(routed) -> None:
    with pytest.raises(HTTPException) as ei:
        fr.search_messages(q="x" * (fr.MAX_SEARCH_QUERY_CHARS + 1))
    assert ei.value.status_code == 422


def test_search_clamps_limit(routed) -> None:
    conv = fr.create_conversation(
        fr.CreateConversationRequest(title="多条", body="needle one")
    )
    fr.append_message(conv.id, fr.AppendMessageRequest(body="needle two"))

    assert len(fr.search_messages(q="needle", limit=0)) == 1
    assert len(fr.search_messages(q="needle", limit=9999)) == 2


def test_create_conversation_with_tag(routed) -> None:
    dto = fr.create_conversation(fr.CreateConversationRequest(title="崩溃", tag="bug"))

    assert dto.tag == "bug"
    assert fr.get_conversation(dto.id).conversation.tag == "bug"


def test_create_conversation_defaults_to_other_tag(routed) -> None:
    dto = fr.create_conversation(fr.CreateConversationRequest(title="随手一说"))

    assert dto.tag == "other"


def test_create_conversation_rejects_invalid_tag(routed) -> None:
    with pytest.raises(HTTPException) as ei:
        fr.create_conversation(fr.CreateConversationRequest(title="会话", tag="urgent"))
    assert ei.value.status_code == 422
