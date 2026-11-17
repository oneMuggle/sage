# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""v19：受控浏览器动作审计表（browser_action_log）。"""

from __future__ import annotations

from typing import Any


def _v19_browser_actions(conn: Any) -> None:
    """Create browser_action_log table and session/ts index."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS browser_action_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL,
          conversation_id TEXT,
          ts INTEGER NOT NULL,
          domain TEXT NOT NULL DEFAULT '',
          tool TEXT NOT NULL,
          action TEXT NOT NULL DEFAULT '',
          target_ref TEXT NOT NULL DEFAULT '',
          target_desc TEXT NOT NULL DEFAULT '',
          result TEXT NOT NULL,
          approval TEXT NOT NULL DEFAULT 'auto',
          duration_ms INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_browser_action_session
        ON browser_action_log(session_id, ts)
        """
    )
    conn.commit()
