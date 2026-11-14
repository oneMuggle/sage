"""Playbook author conversation repository (2026-11-14).

Backs the conversational playbook authoring flow: each conversation keeps the
full message history plus the playbook draft as of the latest turn, so the user
can iterate with the AI and roll back to an earlier draft.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.data.database import get_database

logger = logging.getLogger(__name__)

MAX_CONVERSATIONS_PER_PROJECT = 20
STATUS_ACTIVE = "active"
STATUS_COMMITTED = "committed"
STATUS_ARCHIVED = "archived"


@dataclass
class AuthorConversation:
    """One conversational playbook-authoring session."""

    id: str
    project_id: str
    messages: List[Dict[str, Any]]
    current_spec: Optional[Dict[str, Any]]
    status: str
    created_at: int
    updated_at: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "messages": self.messages,
            "current_spec": self.current_spec,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _parse_messages(raw: Any) -> List[Dict[str, Any]]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _parse_spec(raw: Any) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _row_to_conversation(row) -> AuthorConversation:  # noqa: ANN001 — sqlite3.Row
    return AuthorConversation(
        id=row["id"],
        project_id=row["project_id"],
        messages=_parse_messages(row["messages_json"]),
        current_spec=_parse_spec(row["current_spec_json"]),
        status=row["status"] or STATUS_ACTIVE,
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
    )


class PlaybookAuthorConversationRepository:
    """CRUD for conversational playbook-authoring sessions."""

    def __init__(self) -> None:
        self.db = get_database()

    def create(
        self,
        project_id: str,
        *,
        spec: Optional[Dict[str, Any]] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> AuthorConversation:
        now_ms = int(time.time() * 1000)
        conversation_id = str(uuid.uuid4())
        payload = messages or []
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO playbook_author_conversations
                (id, project_id, messages_json, current_spec_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                project_id,
                json.dumps(payload, ensure_ascii=False),
                None if spec is None else json.dumps(spec, ensure_ascii=False),
                STATUS_ACTIVE,
                now_ms,
                now_ms,
            ),
        )
        # Keep only the newest conversations for the project.
        cursor.execute(
            """
            DELETE FROM playbook_author_conversations
            WHERE project_id = ? AND id NOT IN (
                SELECT id FROM playbook_author_conversations
                WHERE project_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
            )
            """,
            (project_id, project_id, MAX_CONVERSATIONS_PER_PROJECT),
        )
        conn.commit()
        return AuthorConversation(
            id=conversation_id,
            project_id=project_id,
            messages=list(payload),
            current_spec=spec,
            status=STATUS_ACTIVE,
            created_at=now_ms,
            updated_at=now_ms,
        )

    def get(self, conversation_id: str) -> Optional[AuthorConversation]:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM playbook_author_conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        return None if row is None else _row_to_conversation(row)

    def get_for_project(
        self, project_id: str, conversation_id: str
    ) -> Optional[AuthorConversation]:
        conversation = self.get(conversation_id)
        if conversation is None or conversation.project_id != project_id:
            return None
        return conversation

    def get_active(self, project_id: str) -> Optional[AuthorConversation]:
        conn = self.db.get_connection()
        row = conn.execute(
            """
            SELECT * FROM playbook_author_conversations
            WHERE project_id = ? AND status = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (project_id, STATUS_ACTIVE),
        ).fetchone()
        return None if row is None else _row_to_conversation(row)

    def list_by_project(
        self, project_id: str, limit: int = MAX_CONVERSATIONS_PER_PROJECT
    ) -> List[AuthorConversation]:
        conn = self.db.get_connection()
        rows = conn.execute(
            """
            SELECT * FROM playbook_author_conversations
            WHERE project_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
        return [_row_to_conversation(row) for row in rows]

    def save(self, conversation: AuthorConversation) -> AuthorConversation:
        now_ms = int(time.time() * 1000)
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE playbook_author_conversations
            SET messages_json = ?, current_spec_json = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(conversation.messages, ensure_ascii=False),
                None
                if conversation.current_spec is None
                else json.dumps(conversation.current_spec, ensure_ascii=False),
                conversation.status,
                now_ms,
                conversation.id,
            ),
        )
        conn.commit()
        conversation.updated_at = now_ms
        return conversation

    def delete(self, conversation_id: str) -> bool:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM playbook_author_conversations WHERE id = ?",
            (conversation_id,),
        )
        conn.commit()
        return cursor.rowcount > 0


__all__ = [
    "AuthorConversation",
    "MAX_CONVERSATIONS_PER_PROJECT",
    "PlaybookAuthorConversationRepository",
    "STATUS_ACTIVE",
    "STATUS_ARCHIVED",
    "STATUS_COMMITTED",
]
