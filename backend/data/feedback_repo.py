"""SQLite repository for user feedback conversations and messages.

Phase 1 of the direct-feedback-channel design (docs/plans/2026-10-29_direct-feedback-channel.md §3).
Supports bidirectional conversations: users create conversations and send messages,
admins reply via Jira/GitLab/SMTP forwarding script, clients poll for new admin messages.

Schema:
- feedback_conversations: top-level thread (id = UUID v4, client-generated)
- feedback_messages: role='user'|'admin' messages within a conversation
- feedback_attachments: MediaStore-backed binary refs (screenshots, logs)
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class FeedbackConversation:
    """Top-level feedback thread."""

    id: str
    title: str
    status: str  # 'open' | 'resolved' | 'closed'
    app_version: str
    os_info: str
    remote_ticket_id: Optional[str] = None
    remote_ticket_url: Optional[str] = None
    last_activity_at: int = 0  # epoch ms
    created_at: int = 0  # epoch ms
    updated_at: int = 0  # epoch ms


@dataclass
class FeedbackMessage:
    """Single message within a conversation."""

    id: str
    conversation_id: str
    role: str  # 'user' | 'admin'
    body: str
    media_ids: List[str] = field(default_factory=list)
    created_at: int = 0  # epoch ms
    synced_at: Optional[int] = None  # epoch ms


@dataclass
class FeedbackAttachment:
    """Binary attachment ref (points to MediaStore)."""

    id: str
    conversation_id: str
    filename: str
    mime_type: str
    size_bytes: int
    message_id: Optional[str] = None


def _conversation_from_row(row: sqlite3.Row) -> FeedbackConversation:
    return FeedbackConversation(
        id=row["id"],
        title=row["title"],
        status=row["status"],
        app_version=row["app_version"],
        os_info=row["os_info"],
        remote_ticket_id=row["remote_ticket_id"],
        remote_ticket_url=row["remote_ticket_url"],
        last_activity_at=row["last_activity_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _message_from_row(row: sqlite3.Row) -> FeedbackMessage:
    raw_media = row["media_ids"] or "[]"
    try:
        media_ids = json.loads(raw_media)
    except (ValueError, TypeError):
        media_ids = []
    return FeedbackMessage(
        id=row["id"],
        conversation_id=row["conversation_id"],
        role=row["role"],
        body=row["body"],
        media_ids=media_ids,
        created_at=row["created_at"],
        synced_at=row["synced_at"],
    )


def _attachment_from_row(row: sqlite3.Row) -> FeedbackAttachment:
    return FeedbackAttachment(
        id=row["id"],
        conversation_id=row["conversation_id"],
        message_id=row["message_id"],
        filename=row["filename"],
        mime_type=row["mime_type"],
        size_bytes=row["size_bytes"],
    )


class FeedbackRepo:
    """feedback_conversations / messages / attachments CRUD."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _next_timestamp(self, conversation_id: str) -> int:
        """返回严格大于该会话已有消息时间戳的 epoch ms。

        epoch 毫秒精度不足以区分同一毫秒内的两条消息, 会让
        ``list_messages(since=...)`` 的 ``>`` 过滤漏掉后写入的那条。
        这里把时间戳推到 ``max(前一条 + 1, 当前时间)``, 保证会话内单调。
        """
        now = int(time.time() * 1000)
        row = self._conn.execute(
            "SELECT MAX(created_at) AS m FROM feedback_messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        prev = row["m"] if row is not None else None
        if prev is not None:
            now = max(now, int(prev) + 1)
        return now

    # ==================== Conversations ====================

    def create_conversation(
        self,
        id: Optional[str] = None,
        title: str = "",
        app_version: str = "unknown",
        os_info: str = "unknown",
    ) -> FeedbackConversation:
        """插入新会话。显式 id 时幂等 —— 已存在则保留原记录并返回它。"""
        now = int(time.time() * 1000)
        conv_id = id or str(uuid.uuid4())
        self._conn.execute(
            """INSERT OR IGNORE INTO feedback_conversations
               (id, title, status, app_version, os_info,
                last_activity_at, created_at, updated_at)
               VALUES (?, ?, 'open', ?, ?, ?, ?, ?)""",
            (conv_id, title, app_version, os_info, now, now, now),
        )
        self._conn.commit()
        existing = self.get_conversation(conv_id)
        if existing is not None:
            return existing
        return FeedbackConversation(
            id=conv_id,
            title=title,
            status="open",
            app_version=app_version,
            os_info=os_info,
            last_activity_at=now,
            created_at=now,
            updated_at=now,
        )

    def get_conversation(self, conversation_id: str) -> Optional[FeedbackConversation]:
        """Fetch conversation by id, or None if not found."""
        cursor = self._conn.execute(
            "SELECT * FROM feedback_conversations WHERE id = ?",
            (conversation_id,),
        )
        row = cursor.fetchone()
        return _conversation_from_row(row) if row else None

    def list_conversations(self, limit: int = 50) -> List[FeedbackConversation]:
        """List recent conversations (newest activity first)."""
        cursor = self._conn.execute(
            "SELECT * FROM feedback_conversations "
            "ORDER BY last_activity_at DESC, rowid DESC LIMIT ?",
            (limit,),
        )
        return [_conversation_from_row(r) for r in cursor.fetchall()]

    def update_conversation_status(self, conversation_id: str, status: str) -> bool:
        """Update status ('open' | 'resolved' | 'closed'). Returns True if found."""
        now = int(time.time() * 1000)
        cursor = self._conn.execute(
            "UPDATE feedback_conversations SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, conversation_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def upsert_remote_ticket(
        self, conversation_id: str, ticket_id: str, ticket_url: str
    ) -> bool:
        """Write back Jira/GitLab ticket id/url (called by forwarding script webhook)."""
        now = int(time.time() * 1000)
        cursor = self._conn.execute(
            "UPDATE feedback_conversations "
            "SET remote_ticket_id = ?, remote_ticket_url = ?, updated_at = ? "
            "WHERE id = ?",
            (ticket_id, ticket_url, now, conversation_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def touch_conversation(self, conversation_id: str) -> None:
        """Bump last_activity_at and updated_at to now."""
        now = self._next_timestamp(conversation_id)
        self._conn.execute(
            "UPDATE feedback_conversations "
            "SET last_activity_at = ?, updated_at = ? WHERE id = ?",
            (now, now, conversation_id),
        )
        self._conn.commit()

    # ==================== Messages ====================

    def get_message(self, message_id: str) -> Optional[FeedbackMessage]:
        """Fetch a single message by id, or None if not found."""
        cursor = self._conn.execute(
            "SELECT * FROM feedback_messages WHERE id = ?",
            (message_id,),
        )
        row = cursor.fetchone()
        return _message_from_row(row) if row else None

    def add_message(
        self,
        conversation_id: str,
        role: str,
        body: str,
        media_ids: Optional[List[str]] = None,
        id: Optional[str] = None,
    ) -> FeedbackMessage:
        """Append a message to a conversation. Bumps last_activity_at.

        Idempotent when ``id`` is explicit: if a message with that id already
        exists in the conversation, returns it without inserting. This lets the
        syncer dedup admin replies pulled from the remote manager across polls.
        """
        msg_id = id or str(uuid.uuid4())
        if id is not None:
            existing = self.get_message(msg_id)
            if existing is not None:
                return existing

        now = self._next_timestamp(conversation_id)
        media_json = json.dumps(media_ids or [])
        self._conn.execute(
            """INSERT INTO feedback_messages
               (id, conversation_id, role, body, media_ids, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (msg_id, conversation_id, role, body, media_json, now),
        )
        # Update conversation last_activity_at
        self._conn.execute(
            "UPDATE feedback_conversations "
            "SET last_activity_at = ?, updated_at = ? WHERE id = ?",
            (now, now, conversation_id),
        )
        self._conn.commit()
        return FeedbackMessage(
            id=msg_id,
            conversation_id=conversation_id,
            role=role,
            body=body,
            media_ids=media_ids or [],
            created_at=now,
        )

    def list_messages(
        self, conversation_id: str, since: Optional[int] = None, limit: int = 200
    ) -> List[FeedbackMessage]:
        """List messages in a conversation, optionally after a timestamp (epoch ms)."""
        if since is not None:
            cursor = self._conn.execute(
                "SELECT * FROM feedback_messages "
                "WHERE conversation_id = ? AND created_at > ? "
                "ORDER BY created_at ASC LIMIT ?",
                (conversation_id, since, limit),
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM feedback_messages "
                "WHERE conversation_id = ? "
                "ORDER BY created_at ASC LIMIT ?",
                (conversation_id, limit),
            )
        return [_message_from_row(r) for r in cursor.fetchall()]

    def mark_synced(self, message_id: str) -> bool:
        """Set synced_at = now. Called after HTTP POST to forwarding script succeeds."""
        now = int(time.time() * 1000)
        cursor = self._conn.execute(
            "UPDATE feedback_messages SET synced_at = ? WHERE id = ?",
            (now, message_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def list_unsynced_messages(self, conversation_id: str) -> List[FeedbackMessage]:
        """Messages not yet forwarded (synced_at IS NULL)."""
        cursor = self._conn.execute(
            "SELECT * FROM feedback_messages "
            "WHERE conversation_id = ? AND synced_at IS NULL "
            "ORDER BY created_at ASC",
            (conversation_id,),
        )
        return [_message_from_row(r) for r in cursor.fetchall()]

    # ==================== Attachments ====================

    def add_attachment(
        self,
        conversation_id: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> FeedbackAttachment:
        """Register an attachment ref (binary stored in MediaStore)."""
        att_id = id or str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO feedback_attachments
               (id, conversation_id, message_id, filename, mime_type, size_bytes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (att_id, conversation_id, message_id, filename, mime_type, size_bytes),
        )
        self._conn.commit()
        return FeedbackAttachment(
            id=att_id,
            conversation_id=conversation_id,
            message_id=message_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
        )

    def list_attachments(self, conversation_id: str) -> List[FeedbackAttachment]:
        """List all attachments in a conversation."""
        cursor = self._conn.execute(
            "SELECT * FROM feedback_attachments WHERE conversation_id = ?",
            (conversation_id,),
        )
        return [_attachment_from_row(r) for r in cursor.fetchall()]
