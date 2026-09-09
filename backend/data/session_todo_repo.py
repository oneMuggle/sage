"""SQLite persistence for per-session todo lists (B4, 2026-09-09).

``todo_write`` 是会话内任务清单（claw-code TodoWrite 语义：全量替换）。
此前状态纯内存（``todo_state.SessionStateStore``），重启/重开会话后任务
板为空。本 repo 做write-through 落库 + 按会话读取，恢复任务板。

Schema ownership note: the authoritative DDL lives in
``backend/data/database.py`` (``session_todos``). This class assumes the
table exists and only performs CRUD.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from backend.data.database import _SQLITE_LOCK, get_database


class SessionTodoRepository:
    """``session_todos`` CRUD（一会话一行，todos 序列化为 JSON）。"""

    def __init__(self) -> None:
        self.db = get_database()

    def upsert(self, session_id: str, todos: List[Dict[str, Any]]) -> None:
        """整体替换该会话的 todo 行（全量替换语义）。失败向上抛，调用方降级。"""
        now_ms = int(time.time() * 1000)
        payload = json.dumps(todos, ensure_ascii=False)
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            conn.execute(
                """
                INSERT INTO session_todos (session_id, todos_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    todos_json = excluded.todos_json,
                    updated_at = excluded.updated_at
                """,
                (session_id, payload, now_ms),
            )
            conn.commit()

    def get(self, session_id: str) -> Optional[List[Dict[str, Any]]]:
        """读取会话 todo 列表；无行 → None。JSON 损坏按无数据处理。"""
        row = self.db.get_connection().execute(
            "SELECT todos_json FROM session_todos WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            parsed = json.loads(row["todos_json"])
        except ValueError:
            return None
        return parsed if isinstance(parsed, list) else None

    def delete(self, session_id: str) -> None:
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            conn.execute(
                "DELETE FROM session_todos WHERE session_id = ?", (session_id,)
            )
            conn.commit()

    def delete_all(self) -> None:
        """清空全表（``SessionStateStore.clear(None)`` 测试复位语义配套）。"""
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            conn.execute("DELETE FROM session_todos")
            conn.commit()


__all__ = ["SessionTodoRepository"]
