"""群聊参与者仓储（M2 私聊/群聊）。

表：``conversation_participants``（migration v16）。

- 会话类型为 ``'group'`` 时使用；DM 仍走 ``sessions.specialist_id``。
- 每个参与者关联一个 agent；``role='host'`` 表示默认发言/兜底者。
- 读取时 JOIN ``agents`` 带出头像与名字，供前端气泡/头部展示。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_AVATAR = "🤖"


def _read_avatar(persona_ui: Optional[str]) -> str:
    try:
        parsed = json.loads(persona_ui or "{}")
    except (ValueError, TypeError):
        return DEFAULT_AVATAR
    if isinstance(parsed, dict):
        avatar = parsed.get("avatar")
        if isinstance(avatar, str) and avatar.strip():
            return avatar.strip()
    return DEFAULT_AVATAR


def list_participants(conn: Any, conversation_id: str) -> List[Dict[str, Any]]:
    """列出会话参与者（按 speak_order / added_at 升序）。"""
    rows = conn.execute(
        """
        SELECT p.conversation_id, p.agent_id, p.role, p.speak_order,
               p.enabled, p.added_at, a.name, a.persona_ui
        FROM conversation_participants p
        LEFT JOIN agents a ON a.id = p.agent_id
        WHERE p.conversation_id = ?
        ORDER BY p.speak_order ASC, p.added_at ASC
        """,
        (conversation_id,),
    ).fetchall()
    return [
        {
            "conversation_id": row["conversation_id"],
            "agent_id": row["agent_id"],
            "name": row["name"] or row["agent_id"],
            "avatar": _read_avatar(row["persona_ui"]),
            "role": row["role"],
            "speak_order": row["speak_order"],
            "enabled": bool(row["enabled"]),
            "added_at": row["added_at"],
        }
        for row in rows
    ]


def add_participants(
    conn: Any,
    conversation_id: str,
    agent_ids: List[str],
    host_agent_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """批量加入参与者（幂等：已存在则跳过）。首个新成员在无 host 时成为 host。"""
    existing = {p["agent_id"] for p in list_participants(conn, conversation_id)}
    has_host = any(p["role"] == "host" for p in list_participants(conn, conversation_id))
    now = int(time.time() * 1000)
    next_order = len(existing)
    for agent_id in agent_ids:
        if not agent_id or agent_id in existing:
            continue
        if host_agent_id is not None:
            role = "host" if agent_id == host_agent_id else "member"
        else:
            role = "host" if not has_host else "member"
            if role == "host":
                has_host = True
        conn.execute(
            """
            INSERT INTO conversation_participants
                (conversation_id, agent_id, role, speak_order, enabled, added_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (conversation_id, agent_id, role, next_order, now),
        )
        existing.add(agent_id)
        next_order += 1
    conn.commit()
    return list_participants(conn, conversation_id)


def remove_participant(conn: Any, conversation_id: str, agent_id: str) -> bool:
    cursor = conn.execute(
        "DELETE FROM conversation_participants WHERE conversation_id = ? AND agent_id = ?",
        (conversation_id, agent_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def resolve_mention_agent(
    conn: Any, conversation_id: str, message: str
) -> Optional[str]:
    """从用户消息中解析 @专家名 → agent_id（最长名字优先，避免前缀误配）。

    未命中或非群聊会话返回 None（调用方回落到会话绑定/主助手）。
    """
    if not message or "@" not in message:
        return None
    participants = [p for p in list_participants(conn, conversation_id) if p["enabled"]]
    for participant in sorted(participants, key=lambda p: len(p["name"]), reverse=True):
        if f"@{participant['name']}" in message:
            return participant["agent_id"]
    return None
