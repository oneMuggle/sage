"""Settings 仓储层

基于 preferences 表的 KV 存储。模块级 KEYS 白名单限定可写入的 key。
"""

from __future__ import annotations
from typing import Dict, FrozenSet, Optional

import json
import time
from typing import Any

from backend.data.database import Database, get_database


class SettingsRepository:
    """preferences 表的 KV 仓储。"""

    KEYS: FrozenSet[str] = frozenset(
        {
            "app_settings",
            "theme_mode",
            "theme_preset",
            "current_session_id",
        }
    )

    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()

    def _conn(self):
        return self.db.get_connection()

    def get(self, key: str) -> str | None:
        if key not in self.KEYS:
            return None
        row = self._conn().execute("SELECT value FROM preferences WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def get_json(self, key: str) -> Any | None:
        raw = self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None

    def set(
        self,
        key: str,
        value: str,
        value_type: str = "string",
        category: str = "general",
    ) -> None:
        if key not in self.KEYS:
            raise ValueError(f"key {key!r} not in whitelist")
        now = int(time.time() * 1000)
        conn = self._conn()
        existing = conn.execute("SELECT key FROM preferences WHERE key = ?", (key,)).fetchone()
        if existing:
            conn.execute(
                """UPDATE preferences
                   SET value = ?, value_type = ?, category = ?, updated_at = ?
                   WHERE key = ?""",
                (value, value_type, category, now, key),
            )
        else:
            conn.execute(
                """INSERT INTO preferences
                   (key, value, value_type, category, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (key, value, value_type, category, now, now),
            )
        conn.commit()

    def set_json(self, key: str, value: Any, category: str = "general") -> None:
        self.set(key, json.dumps(value, ensure_ascii=False), value_type="json", category=category)

    def delete(self, key: str) -> None:
        if key not in self.KEYS:
            return
        conn = self._conn()
        conn.execute("DELETE FROM preferences WHERE key = ?", (key,))
        conn.commit()

    def list_by_category(self, category: str) -> Dict[str, str]:
        rows = (
            self._conn()
            .execute("SELECT key, value FROM preferences WHERE category = ?", (category,))
            .fetchall()
        )
        return {row["key"]: row["value"] for row in rows}
