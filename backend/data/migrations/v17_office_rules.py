# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""v17：规则管理表（office_rule_groups + office_rules）。"""

from __future__ import annotations

from typing import Any


def _v17_office_rules(conn: Any) -> None:
    """Create office_rule_groups and office_rules tables."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS office_rule_groups (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            priority INTEGER NOT NULL DEFAULT 0,
            builtin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS office_rules (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('format','terminology','citation','structure','custom')),
            severity TEXT NOT NULL CHECK(severity IN ('error','warning','info')),
            scope TEXT NOT NULL CHECK(scope IN ('full','heading','body','table','caption')),
            description TEXT NOT NULL DEFAULT '',
            check_mode TEXT NOT NULL CHECK(check_mode IN ('regex','ai')),
            pattern TEXT,
            ai_prompt TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            group_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (group_id) REFERENCES office_rule_groups(id) ON DELETE CASCADE
        )
        """
    )
    conn.commit()
