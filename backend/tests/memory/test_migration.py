"""记忆标题列迁移测试（2026-11-17 记忆详情化）。

main 分支无 win7 的 traceability 迁移测试文件；本文件只覆盖本功能：
存量库缺 ``title`` 列时，``init_db`` 必须幂等补列（ALTER 路径）。
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.data.database import Database

pytestmark = pytest.mark.unit


# 旧版建表语句（2026-11-17 记忆详情化之前）：不含 title 列。
_LEGACY_EPISODIC_DDL = """
CREATE TABLE memories_episodic (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    content TEXT NOT NULL,
    summary TEXT,
    memory_type TEXT DEFAULT 'conversation',
    importance INTEGER DEFAULT 5,
    source TEXT DEFAULT 'auto',
    tags TEXT,
    created_at INTEGER NOT NULL,
    accessed_at INTEGER,
    access_count INTEGER DEFAULT 0,
    sentiment TEXT,
    is_valid INTEGER DEFAULT 1,
    expires_at INTEGER,
    scope TEXT DEFAULT 'user',
    project_key TEXT,
    invalid_at INTEGER,
    supersedes_id TEXT
)
"""

_LEGACY_SEMANTIC_DDL = """
CREATE TABLE memories_semantic (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    summary TEXT,
    tags TEXT DEFAULT '[]',
    created_at INTEGER NOT NULL,
    scope TEXT DEFAULT 'user',
    project_key TEXT,
    invalid_at INTEGER,
    supersedes_id TEXT
)
"""


def test_init_db_adds_title_column_to_legacy_tables(tmp_path):
    """存量库缺 title 列时，init_db 必须幂等补列（ALTER 路径）。

    刻意不用 ``tmp_db_path`` fixture —— autouse 的 ``setup_test_db`` 会先在该
    文件上跑一遍完整 init_db，旧表结构就无从模拟了。
    """
    db_file = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db_file)
    conn.execute(_LEGACY_EPISODIC_DDL)
    conn.execute(_LEGACY_SEMANTIC_DDL)
    conn.commit()
    conn.close()

    db = Database(db_path=db_file)
    db.init_db()
    try:
        episodic_cols = {
            row[1]
            for row in db.get_connection().execute(
                "PRAGMA table_info(memories_episodic)"
            )
        }
        semantic_cols = {
            row[1]
            for row in db.get_connection().execute(
                "PRAGMA table_info(memories_semantic)"
            )
        }
        assert "title" in episodic_cols
        assert "title" in semantic_cols
    finally:
        db.close()
