"""M3-Task 1 — 记忆表 agent_id 维度迁移（v11）测试。

契约：
- 全新库 init 后 ``memories_episodic`` / ``memories_semantic`` 均有可空
  ``agent_id`` 列，且复合索引存在；
- 旧库（schema_version 已到 v10、两表无 agent_id）跑 pending 迁移后补列补索引；
- ``init_db`` 幂等：重复调用不重复加列、schema_version 中 v11 仅一条；
- 存量行 ``agent_id IS NULL``（= 共享层语义），仍可正常读取。
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.data.database import Database
from backend.data.migrations.runner import run_pending_migrations

pytestmark = pytest.mark.unit


def _columns(db: Database, table: str) -> list:
    cur = db.get_connection().execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]


def _indexes(db: Database, prefix: str) -> set:
    cur = db.get_connection().execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE ?",
        (f"{prefix}%",),
    )
    return {row[0] for row in cur.fetchall()}


def test_fresh_db_has_agent_id_columns(tmp_db_path):
    db = Database(db_path=tmp_db_path)
    db.init_db()

    assert "agent_id" in _columns(db, "memories_episodic")
    assert "agent_id" in _columns(db, "memories_semantic")


def test_fresh_db_has_agent_indexes(tmp_db_path):
    db = Database(db_path=tmp_db_path)
    db.init_db()

    assert "idx_episodic_agent" in _indexes(db, "idx_episodic_agent")
    assert "idx_semantic_agent" in _indexes(db, "idx_semantic_agent")


def test_schema_version_records_v11(tmp_db_path):
    db = Database(db_path=tmp_db_path)
    db.init_db()

    cur = db.get_connection().execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = 11"
    )
    assert cur.fetchone()[0] == 1


def test_init_db_twice_does_not_duplicate_agent_id(tmp_db_path):
    db = Database(db_path=tmp_db_path)
    db.init_db()
    db.init_db()

    assert _columns(db, "memories_episodic").count("agent_id") == 1
    assert _columns(db, "memories_semantic").count("agent_id") == 1


def test_legacy_row_without_agent_is_readable_as_shared(tmp_db_path):
    """存量行 agent_id 为 NULL —— 视为共享层，读取不报错。"""
    db = Database(db_path=tmp_db_path)
    db.init_db()

    conn = db.get_connection()
    conn.execute(
        "INSERT INTO memories_episodic (id, content, created_at) "
        "VALUES ('legacy-1', 'old fact', 1)"
    )
    conn.execute(
        "INSERT INTO memories_semantic (id, content, created_at) "
        "VALUES ('legacy-2', 'old semantic fact', 1)"
    )
    conn.commit()

    epi = conn.execute(
        "SELECT agent_id FROM memories_episodic WHERE id = 'legacy-1'"
    ).fetchone()
    sem = conn.execute(
        "SELECT agent_id FROM memories_semantic WHERE id = 'legacy-2'"
    ).fetchone()
    assert epi[0] is None
    assert sem[0] is None


def test_pending_migration_upgrades_v10_db(tmp_path):
    """模拟已到 v10、两表无 agent_id 的旧库 → 跑 pending 迁移补列补索引。"""
    db_file = tmp_path / "legacy_v10.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE schema_version (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at INTEGER NOT NULL
        );
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
        );
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
        );
        INSERT INTO memories_episodic (id, content, created_at)
            VALUES ('legacy-1', 'old fact', 1);
        """
    )
    # 假设 v1..v10 均已应用（本用例只验证 v11 的补列行为）
    for version in range(1, 11):
        conn.execute(
            "INSERT INTO schema_version (version, name, applied_at) "
            "VALUES (?, 'seeded', 1)",
            (version,),
        )
    conn.commit()

    applied = run_pending_migrations(conn)

    assert 11 in applied
    epi_cols = {row[1] for row in conn.execute("PRAGMA table_info(memories_episodic)")}
    sem_cols = {row[1] for row in conn.execute("PRAGMA table_info(memories_semantic)")}
    assert "agent_id" in epi_cols
    assert "agent_id" in sem_cols
    idx = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name IN ('idx_episodic_agent', 'idx_semantic_agent')"
        )
    }
    assert idx == {"idx_episodic_agent", "idx_semantic_agent"}
    # 存量行保持 NULL（共享层），不被回填
    row = conn.execute("SELECT agent_id FROM memories_episodic WHERE id = 'legacy-1'").fetchone()
    assert row[0] is None
    conn.close()
