# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""v22：office_rules 增加抽取元数据列（structured_params / confidence / source_excerpt）。"""

from __future__ import annotations

from typing import Any


def _v22_rule_extraction_metadata(conn: Any) -> None:
    """Add extraction metadata columns to office_rules for draft-review workflow."""
    cursor = conn.cursor()
    cursor.execute(
        "ALTER TABLE office_rules ADD COLUMN structured_params TEXT"
    )
    cursor.execute(
        "ALTER TABLE office_rules ADD COLUMN confidence REAL"
    )
    cursor.execute(
        "ALTER TABLE office_rules ADD COLUMN source_excerpt TEXT"
    )
    conn.commit()
