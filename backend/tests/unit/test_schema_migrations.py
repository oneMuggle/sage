# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""schema 版本化迁移框架测试（DSH 对标 R9，C3）。

全局 MIGRATIONS 注册表用 fixture 隔离（save/restore），测试注册的迁移
不污染其他用例。init_db 集成用例验证生产接线（空注册表 → no-op）。
"""

from __future__ import annotations

import pytest

from backend.data.migrations.runner import (
    MIGRATIONS,
    _v18_normalize_millisecond_timestamps,
    applied_versions,
    ensure_version_table,
    register_migration,
    run_pending_migrations,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def clean_registry(setup_test_db):
    """隔离全局注册表 + 清空 schema_version 表（测试结束恢复原内容）。"""
    saved = list(MIGRATIONS)
    MIGRATIONS.clear()
    conn = setup_test_db.get_connection()
    conn.execute("DELETE FROM schema_version")
    conn.commit()
    yield MIGRATIONS
    MIGRATIONS[:] = saved


def _add_migration(version, name, fn):
    register_migration(version, name, fn)


def test_fresh_db_applies_all_in_order(setup_test_db, clean_registry):
    calls = []
    _add_migration(1, "m1", lambda conn: calls.append(1))
    _add_migration(2, "m2", lambda conn: calls.append(2))

    applied = run_pending_migrations(setup_test_db.get_connection())
    assert applied == [1, 2]
    assert calls == [1, 2]
    assert applied_versions(setup_test_db.get_connection()) == {1, 2}


def test_idempotent_second_run_is_noop(setup_test_db, clean_registry):
    calls = []
    _add_migration(1, "m1", lambda conn: calls.append(1))

    conn = setup_test_db.get_connection()
    assert run_pending_migrations(conn) == [1]
    assert run_pending_migrations(conn) == []  # 第二次：全部已应用
    assert calls == [1]  # 迁移函数只执行一次


def test_existing_versions_are_skipped(setup_test_db, clean_registry):
    ensure_version_table(setup_test_db.get_connection())
    setup_test_db.get_connection().execute(
        "INSERT INTO schema_version (version, name, applied_at) VALUES (1, '历史迁移', 0)"
    )
    setup_test_db.get_connection().commit()

    calls = []
    _add_migration(1, "m1", lambda conn: calls.append("不应执行"))
    _add_migration(2, "m2", lambda conn: calls.append(2))

    applied = run_pending_migrations(setup_test_db.get_connection())
    assert applied == [2]
    assert calls == [2]  # v1 已在账本 → 跳过


def test_non_increasing_version_rejected(clean_registry):
    _add_migration(2, "m2", lambda conn: None)
    with pytest.raises(ValueError, match="严格递增"):
        _add_migration(2, "dup", lambda conn: None)
    with pytest.raises(ValueError, match="严格递增"):
        _add_migration(1, "backwards", lambda conn: None)


def test_failed_migration_not_recorded(setup_test_db, clean_registry):
    def _boom(conn):
        raise RuntimeError("迁移炸了")

    _add_migration(1, "boom", _boom)
    with pytest.raises(RuntimeError):
        run_pending_migrations(setup_test_db.get_connection())
    # 失败版本不留账本记录（半应用可定位）
    assert applied_versions(setup_test_db.get_connection()) == set()


def test_migration_can_execute_ddl(setup_test_db, clean_registry):
    def _create_sentinel(conn):
        conn.execute("CREATE TABLE IF NOT EXISTS _migration_sentinel (id INTEGER PRIMARY KEY)")
        conn.commit()

    _add_migration(1, "sentinel", _create_sentinel)
    run_pending_migrations(setup_test_db.get_connection())
    conn = setup_test_db.get_connection()
    conn.execute("INSERT INTO _migration_sentinel DEFAULT VALUES")
    conn.commit()


# ---- init_db 生产接线（空注册表 → no-op，不破坏既有初始化）----


def test_init_db_with_empty_registry_is_noop(tmp_path):
    from backend.data.database import Database

    db = Database(db_path=str(tmp_path / "fresh.db"))
    try:
        db.init_db()  # v1-v18 自动注册（runner.py 模块级）
        versions = applied_versions(db.get_connection())
        # v1 基线 + v2-v21 迁移（v18 归一化历史秒级时间戳；v19 浏览器动作审计；
        # v20 usage_events.run_id 归因回填；v21 orch_tasks 复合主键重建；
        # v23 presentation_templates 模板库索引）
        assert versions == {
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            13,
            14,
            15,
            16,
            17,
            18,
            19,
            20,
            21,
            22,
            23,
        }
        # schema_version 表已建（账本就绪）
    finally:
        db.close()


def test_v10_adds_tag_column_to_legacy_feedback_table() -> None:
    """v10：老库 feedback_conversations 缺 tag 列时补上，历史行落 'other'；重复执行幂等。"""
    import sqlite3

    from backend.data.migrations.runner import _v10_feedback_conversations_tag

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "CREATE TABLE feedback_conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO feedback_conversations (id, title) VALUES ('c1', '老会话')")
        conn.commit()

        _v10_feedback_conversations_tag(conn)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(feedback_conversations)")}
        assert "tag" in columns
        row = conn.execute("SELECT tag FROM feedback_conversations WHERE id = 'c1'").fetchone()
        assert row["tag"] == "other"

        _v10_feedback_conversations_tag(conn)  # 幂等：不重复 ALTER
        assert conn.execute("SELECT tag FROM feedback_conversations").fetchone()["tag"] == "other"
    finally:
        conn.close()


def test_v17_office_rules_tables() -> None:
    """v17：建 office_rule_groups / office_rules 两表，重复执行幂等。"""
    import sqlite3

    from backend.data.migrations.runner import (
        MIGRATIONS,
        _v17_office_rules,
    )

    assert (17, "office_rules") in [(v, name) for v, name, _fn in MIGRATIONS]

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _v17_office_rules(conn)
        _v17_office_rules(conn)  # idempotent

        tables = {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"office_rule_groups", "office_rules"} <= tables

        rule_columns = {row["name"] for row in conn.execute("PRAGMA table_info(office_rules)")}
        assert {
            "id",
            "name",
            "type",
            "severity",
            "scope",
            "description",
            "check_mode",
            "pattern",
            "ai_prompt",
            "enabled",
            "group_id",
            "created_at",
            "updated_at",
        } == rule_columns

        group_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(office_rule_groups)")
        }
        assert {
            "id",
            "name",
            "description",
            "priority",
            "builtin",
            "created_at",
            "updated_at",
        } == group_columns

        fks = conn.execute("PRAGMA foreign_key_list(office_rules)").fetchall()
        assert len(fks) == 1
        assert fks[0]["table"] == "office_rule_groups"
        assert fks[0]["from"] == "group_id"
        assert fks[0]["on_delete"] == "CASCADE"
    finally:
        conn.close()


def test_v18_normalizes_legacy_seconds_to_milliseconds(setup_test_db):
    """历史秒级时间戳归一为毫秒；evolution_log 保持秒。"""
    db = setup_test_db
    conn = db.get_connection()
    now_s = 1_700_000_000
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at, last_message_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("sess-legacy", "legacy", now_s, now_s, now_s),
    )
    conn.execute(
        "INSERT INTO memories_episodic (id, content, created_at) VALUES (?, ?, ?)",
        ("mem-legacy", "legacy memory", now_s),
    )
    conn.execute(
        "INSERT INTO evolution_log "
        "(id, evolution_type, description, status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("evo-legacy", "memory_pruning", "legacy", "success", now_s),
    )
    conn.commit()

    _v18_normalize_millisecond_timestamps(conn)
    _v18_normalize_millisecond_timestamps(conn)  # 幂等

    session_ts = conn.execute(
        "SELECT created_at FROM sessions WHERE id = 'sess-legacy'"
    ).fetchone()[0]
    memory_ts = conn.execute(
        "SELECT created_at FROM memories_episodic WHERE id = 'mem-legacy'"
    ).fetchone()[0]
    evolution_ts = conn.execute(
        "SELECT created_at FROM evolution_log WHERE id = 'evo-legacy'"
    ).fetchone()[0]

    assert session_ts == now_s * 1000
    assert memory_ts == now_s * 1000
    # evolution_log 按设计保持秒，不能被迁移误放大
    assert evolution_ts == now_s


def test_v19_browser_actions_table_and_index() -> None:
    """v19：建 browser_action_log 表与会话索引，重复执行幂等。"""
    import sqlite3

    from backend.data.migrations.runner import (
        MIGRATIONS,
        _v19_browser_actions,
    )

    assert (19, "browser_actions") in [(v, name) for v, name, _fn in MIGRATIONS]

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _v19_browser_actions(conn)
        _v19_browser_actions(conn)  # idempotent

        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "browser_action_log" in tables

        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(browser_action_log)")
        }
        assert {
            "id",
            "session_id",
            "conversation_id",
            "ts",
            "domain",
            "tool",
            "action",
            "target_ref",
            "target_desc",
            "result",
            "approval",
            "duration_ms",
        } == columns

        indexes = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert "idx_browser_action_session" in indexes
    finally:
        conn.close()


def test_v20_backfills_usage_run_id() -> None:
    """v20（M4.3b）：历史 usage_events.run_id 按 task_id + session + 时间窗
    回填；窗口外/从未启动的任务不归因；未知定价不影响归因；幂等。"""
    import sqlite3

    from backend.data.migrations.runner import MIGRATIONS, _v20_usage_events_run_id

    assert (20, "usage_events_run_id") in [(v, name) for v, name, _fn in MIGRATIONS]

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        # 旧库形态：usage_events 无 run_id。
        conn.execute(
            "CREATE TABLE orch_runs (run_id TEXT PRIMARY KEY, session_id TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE orch_tasks (task_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,"
            " started_at INTEGER, finished_at INTEGER)"
        )
        conn.execute(
            "CREATE TABLE usage_events (id TEXT PRIMARY KEY, session_id TEXT,"
            " task_id TEXT, created_at INTEGER, estimated_cost_usd REAL)"
        )
        conn.executemany(
            "INSERT INTO orch_runs (run_id, session_id) VALUES (?, ?)",
            [("run-a", "sess-1"), ("run-b", "sess-1")],
        )
        conn.executemany(
            "INSERT INTO orch_tasks (task_id, run_id, started_at, finished_at)"
            " VALUES (?, ?, ?, ?)",
            [
                ("t1", "run-a", 1763900000000, 1763900060000),
                ("t2", "run-b", 1763900100000, 1763900160000),
                ("t3", "run-a", 1763900180000, 1763900220000),
                # 从未启动的任务（started_at 为空）—— 不得吸收整条时间线。
                ("t4", "run-a", None, None),
            ],
        )
        conn.executemany(
            "INSERT INTO usage_events (id, session_id, task_id, created_at,"
            " estimated_cost_usd) VALUES (?, ?, ?, ?, ?)",
            [
                # t1 窗口内、已定价 → run-a
                ("e1", "sess-1", "t1", 1763900010000, 0.002),
                # t1 的 task_id 但已出 t1 窗口 → 不可归因，保持 NULL
                ("e2", "sess-1", "t1", 1763900120000, 0.003),
                # t2 窗口内 → run-b
                ("e3", "sess-1", "t2", 1763900110000, 0.004),
                # 别的会话 → 不匹配任何 run
                ("e4", "sess-2", "t1", 1763900020000, 0.005),
                # t1 窗口内但定价未知 → run_id 仍回填（归因与定价无关）
                ("e5", "sess-1", "t1", 1763900030000, None),
                # t3 窗口内 → run-a
                ("e6", "sess-1", "t3", 1763900190000, None),
                # t4 从未启动 → 不归因（时间窗无法界定）
                ("e7", "sess-1", "t4", 1763900010000, 0.009),
            ],
        )
        conn.commit()

        _v20_usage_events_run_id(conn)

        run_ids = {
            row["id"]: row["run_id"]
            for row in conn.execute("SELECT id, run_id FROM usage_events")
        }
        assert run_ids == {
            "e1": "run-a",
            "e2": None,
            "e3": "run-b",
            "e4": None,
            "e5": "run-a",
            "e6": "run-a",
            "e7": None,
        }

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(usage_events)")}
        assert "run_id" in columns
        indexes = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert "idx_usage_events_run" in indexes

        # 幂等重跑：已回填行不重复处理
        _v20_usage_events_run_id(conn)
        assert (
            conn.execute("SELECT run_id FROM usage_events WHERE id = 'e2'").fetchone()[
                "run_id"
            ]
            is None
        )
    finally:
        conn.close()


def test_v21_rebuilds_orch_tasks_with_composite_pk() -> None:
    """v21：旧单列主键 orch_tasks 重建为 (run_id, task_id) 复合主键，
    数据按列名交集保留；orch_context_messages 单列外键同步重建为复合
    外键；二次执行幂等（不重建）。"""
    import sqlite3

    from backend.data.migrations.runner import MIGRATIONS, _v21_orch_tasks_composite_pk

    assert (21, "orch_tasks_composite_pk") in [
        (v, name) for v, name, _fn in MIGRATIONS
    ]

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        # 旧库形态：task_id 单列主键 + ctx 单列外键（与 v20 时代 DDL 一致）。
        conn.execute("CREATE TABLE orch_runs (run_id TEXT PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE orch_tasks ("
            " task_id TEXT PRIMARY KEY,"
            " run_id TEXT NOT NULL REFERENCES orch_runs(run_id),"
            " agent_id TEXT NOT NULL, goal TEXT NOT NULL,"
            " status TEXT NOT NULL DEFAULT 'queued',"
            " retry_count INTEGER NOT NULL DEFAULT 0,"
            " revision INTEGER NOT NULL DEFAULT 0, error TEXT,"
            " output_preview TEXT, blocked_by TEXT, scratch_dir TEXT,"
            " started_at INTEGER, finished_at INTEGER, used_tokens INTEGER,"
            " duration_ms INTEGER, parent_task_id TEXT NULL,"
            " depth INTEGER NOT NULL DEFAULT 0, retry_of TEXT)"
        )
        conn.execute(
            "CREATE TABLE orch_context_messages ("
            " context_id TEXT PRIMARY KEY,"
            " run_id TEXT NOT NULL REFERENCES orch_runs(run_id),"
            " task_id TEXT NOT NULL REFERENCES orch_tasks(task_id),"
            " source TEXT NOT NULL, message_type TEXT NOT NULL,"
            " content_redacted TEXT NOT NULL,"
            " apply_mode TEXT NOT NULL DEFAULT 'next_boundary',"
            " expected_task_revision INTEGER, created_at INTEGER NOT NULL,"
            " created_by TEXT, applied_at INTEGER, applied_step_id TEXT,"
            " status TEXT NOT NULL DEFAULT 'pending')"
        )
        conn.execute("CREATE INDEX idx_orch_tasks_run ON orch_tasks(run_id)")
        conn.executemany(
            "INSERT INTO orch_runs (run_id) VALUES (?)", [("run-a",), ("run-b",)]
        )
        conn.execute(
            "INSERT INTO orch_tasks (task_id, run_id, agent_id, goal, status,"
            " revision, depth) VALUES ('t1', 'run-a', 'a', 'first', 'done', 2, 1)"
        )
        conn.execute(
            "INSERT INTO orch_tasks (task_id, run_id, agent_id, goal, status)"
            " VALUES ('t2', 'run-b', 'b', 'second', 'running')"
        )
        conn.execute(
            "INSERT INTO orch_context_messages (context_id, run_id, task_id,"
            " source, message_type, content_redacted, created_at)"
            " VALUES ('ctx-1', 'run-a', 't1', 'user', 'constraint', 'x', 1000)"
        )
        conn.commit()

        _v21_orch_tasks_composite_pk(conn)

        # 历史数据保留（含 revision / depth 等非核心列）
        rows = conn.execute(
            "SELECT run_id, task_id, goal, status, revision, depth"
            " FROM orch_tasks ORDER BY run_id, task_id"
        ).fetchall()
        assert [(r["run_id"], r["task_id"], r["goal"]) for r in rows] == [
            ("run-a", "t1", "first"),
            ("run-b", "t2", "second"),
        ]
        assert rows[0]["revision"] == 2
        assert rows[0]["depth"] == 1

        # 主键已复合：同名 task_id 可跨 run 并存
        pk = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(orch_tasks)")
            if row["pk"] > 0
        }
        assert pk == {"run_id", "task_id"}
        conn.execute(
            "INSERT INTO orch_tasks (task_id, run_id, agent_id, goal, status)"
            " VALUES ('t1', 'run-b', 'b', 'second t1', 'queued')"
        )

        # ctx 外键已重建为复合 (run_id, task_id)：同一外键分组含两列
        fks = conn.execute(
            "PRAGMA foreign_key_list(orch_context_messages)"
        ).fetchall()
        task_fk_rows = [fk for fk in fks if fk["table"] == "orch_tasks"]
        fk_groups: dict = {}
        for fk in task_fk_rows:
            fk_groups.setdefault(fk["id"], set()).add(fk["from"])
        assert {frozenset(cols) for cols in fk_groups.values()} == {
            frozenset({"run_id", "task_id"})
        }
        assert conn.execute(
            "SELECT context_id FROM orch_context_messages"
        ).fetchone()["context_id"] == "ctx-1"

        # 索引重建
        indexes = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert {
            "idx_orch_tasks_run",
            "idx_orch_tasks_status",
            "idx_orch_context_task_status",
            "idx_orch_context_run",
        } <= indexes

        # 幂等重跑：已复合 → 完整 no-op，数据不丢不重
        _v21_orch_tasks_composite_pk(conn)
        assert conn.execute("SELECT COUNT(*) FROM orch_tasks").fetchone()[0] == 3
        assert (
            conn.execute("SELECT COUNT(*) FROM orch_context_messages").fetchone()[0]
            == 1
        )
    finally:
        conn.close()
