# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""v23：新增 presentation_templates（ppt-master 模板库索引）。"""

from __future__ import annotations

from typing import Any


def _v23_presentation_templates(conn: Any) -> None:
    """Create the ppt-master template index table."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS presentation_templates (
            kind TEXT NOT NULL CHECK(kind IN ('brand','style','layout','deck')),
            template_id TEXT NOT NULL,
            name TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            primary_color TEXT,
            canvas_format TEXT,
            page_count INTEGER,
            page_types TEXT NOT NULL DEFAULT '[]',
            root_path TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (kind, template_id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_presentation_templates_kind "
        "ON presentation_templates(kind)"
    )
    conn.commit()
