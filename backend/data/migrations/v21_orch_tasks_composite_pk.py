# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""v21：``orch_tasks`` 主键改为复合 ``(run_id, task_id)``，外键同步复合化。

背景（M4.3b 遗留，计划文档 §15）：``orch_tasks`` 原主键是 ``task_id``，
计划编号 t1..tN 跨 run 复用，``ON CONFLICT(task_id) DO UPDATE`` 会让同一
会话第二个 run 的同名任务覆盖第一个 run 的行 —— 历史 run 回看时任务行
缺失。金额账本（``usage_events.run_id``，v20）早已按 run 隔离；本迁移把
任务行本身也按 run 隔离。

SQLite 无法直接修改主键，只能表重建：建新表 → 按列名交集复制 → DROP
旧表 → RENAME → 重建索引。父表主键复合后，``orch_context_messages`` 的
旧单列外键（``REFERENCES orch_tasks(task_id)``）在 ``foreign_keys=ON``
下会报 "foreign key mismatch"，因此一并重建为复合外键。

防御与已知局限：
- 表缺失 / 缺核心列 / 缺 ``orch_runs`` 的精简 fixture 库直接跳过（生产库
  由 init_db 防御 ALTER 保证列齐全）；
- 历史已被覆盖的旧 run 任务行无法恢复（旧版本写入时数据已丢失），本迁移
  只保全现存行；
- 旧覆盖缺陷可能留下 ``(run_id, task_id)`` 在任务表已不存在的历史 steer
  上下文行 —— ``foreign_key_check`` 只告警不阻断升级（阻断会让正是本迁移
  要修的库无法启动；这些历史行保留展示，新写入不受影响）。
"""

from __future__ import annotations

from typing import Any, List, Set

#: 触发重建的最低列集（精简 fixture 缺其中任何一列即跳过）。
_TASK_CORE_COLUMNS = frozenset(
    ["task_id", "run_id", "agent_id", "goal", "status"]
)

#: 目标列集（与 database.py 新库 DDL 一致）。副本按交集复制，
#: 老库在 init_db 防御 ALTER 之后的列集应与此完全一致。
_TASK_COLUMNS: List[str] = [
    "task_id",
    "run_id",
    "agent_id",
    "goal",
    "status",
    "retry_count",
    "revision",
    "error",
    "output_preview",
    "blocked_by",
    "scratch_dir",
    "started_at",
    "finished_at",
    "used_tokens",
    "duration_ms",
    "parent_task_id",
    "depth",
    "retry_of",
]

_TASK_DDL = """
CREATE TABLE orch_tasks_v21 (
    task_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES orch_runs(run_id),
    agent_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    retry_count INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    output_preview TEXT,
    blocked_by TEXT,
    scratch_dir TEXT,
    started_at INTEGER,
    finished_at INTEGER,
    used_tokens INTEGER,
    duration_ms INTEGER,
    parent_task_id TEXT NULL,
    depth INTEGER NOT NULL DEFAULT 0,
    retry_of TEXT,
    PRIMARY KEY (run_id, task_id)
)
"""

_CONTEXT_COLUMNS: List[str] = [
    "context_id",
    "run_id",
    "task_id",
    "source",
    "message_type",
    "content_redacted",
    "apply_mode",
    "expected_task_revision",
    "created_at",
    "created_by",
    "applied_at",
    "applied_step_id",
    "status",
]

_CONTEXT_DDL = """
CREATE TABLE orch_context_messages_v21 (
    context_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES orch_runs(run_id),
    task_id TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('user', 'parent_agent', 'system')),
    message_type TEXT NOT NULL CHECK (message_type IN (
        'constraint', 'clarification', 'additional_context',
        'correction', 'priority_update', 'reference'
    )),
    content_redacted TEXT NOT NULL,
    apply_mode TEXT NOT NULL DEFAULT 'next_boundary'
        CHECK (apply_mode IN ('next_boundary', 'new_followup')),
    expected_task_revision INTEGER,
    created_at INTEGER NOT NULL,
    created_by TEXT,
    applied_at INTEGER,
    applied_step_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'delivered', 'acknowledged', 'rejected')),
    FOREIGN KEY (run_id, task_id) REFERENCES orch_tasks(run_id, task_id)
)
"""


def _table_names(conn: Any) -> Set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _primary_key_columns(conn: Any, table: str) -> Set[str]:
    rows = conn.execute("PRAGMA table_info(" + table + ")").fetchall()
    # table_info 行: (cid, name, type, notnull, dflt_value, pk)
    return {row[1] for row in rows if row[5] > 0}


def _column_names(conn: Any, table: str) -> Set[str]:
    rows = conn.execute("PRAGMA table_info(" + table + ")").fetchall()
    return {row[1] for row in rows}


def _context_still_references_single_task_id(conn: Any) -> bool:
    """``orch_context_messages`` 是否仍持有旧单列外键 ``(task_id)``。

    复合外键 ``(run_id, task_id)`` 在 ``foreign_key_list`` 中是同一 id 的
    两行（from=run_id / from=task_id）；只有某个外键分组的 from 列集恰好
    是 ``{"task_id"}`` 时才是旧式单列外键（误判会导致每次启动重复重建）。
    """
    groups: dict = {}
    rows = conn.execute("PRAGMA foreign_key_list(orch_context_messages)").fetchall()
    # foreign_key_list 行: (id, seq, table, from, to, on_update, on_delete, match)
    for row in rows:
        if row[2] != "orch_tasks":
            continue
        groups.setdefault(row[0], set()).add(row[3])
    return any(columns == {"task_id"} for columns in groups.values())


def _rebuild_table(
    conn: Any,
    table: str,
    target_table: str,
    target_columns: List[str],
    ddl: str,
    indexes: List[str],
) -> None:
    """SQLite 表重建通用流程（调用方负责 foreign_keys=OFF）。"""
    conn.execute("DROP TABLE IF EXISTS " + target_table)
    conn.execute(ddl)
    existing = _column_names(conn, table)
    copied = [column for column in target_columns if column in existing]
    if not copied:
        raise RuntimeError(f"v21 表重建失败：{table} 无可复制列")
    column_list = ", ".join(copied)
    conn.execute(
        "INSERT INTO "
        + target_table
        + " ("
        + column_list
        + ") SELECT "
        + column_list
        + " FROM "
        + table
    )
    conn.execute("DROP TABLE " + table)
    conn.execute("ALTER TABLE " + target_table + " RENAME TO " + table)
    for index_sql in indexes:
        conn.execute(index_sql)


def _v21_orch_tasks_composite_pk(conn: Any) -> None:
    """Rebuild orch_tasks (+ orch_context_messages) with composite PK/FK."""
    tables = _table_names(conn)
    if "orch_tasks" not in tables or "orch_runs" not in tables:
        # 极老库/精简 fixture 未建表 —— 交由 init_db DDL 负责。
        return
    if not _TASK_CORE_COLUMNS.issubset(_column_names(conn, "orch_tasks")):
        # 精简 fixture 缺核心列 —— 不重建，避免丢列/造坏表。
        return

    task_pk = _primary_key_columns(conn, "orch_tasks")
    task_needs_rebuild = not {"run_id", "task_id"}.issubset(task_pk)
    context_needs_rebuild = (
        "orch_context_messages" in tables
        and _context_still_references_single_task_id(conn)
    )
    if not task_needs_rebuild and not context_needs_rebuild:
        return

    # PRAGMA foreign_keys 在事务内是 no-op —— 先提交再关闭。
    conn.commit()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys=OFF")
    try:
        if task_needs_rebuild:
            _rebuild_table(
                conn,
                "orch_tasks",
                "orch_tasks_v21",
                _TASK_COLUMNS,
                _TASK_DDL,
                [
                    "CREATE INDEX IF NOT EXISTS idx_orch_tasks_run ON orch_tasks(run_id)",
                    "CREATE INDEX IF NOT EXISTS idx_orch_tasks_status ON orch_tasks(status)",
                ],
            )
        if context_needs_rebuild:
            _rebuild_table(
                conn,
                "orch_context_messages",
                "orch_context_messages_v21",
                _CONTEXT_COLUMNS,
                _CONTEXT_DDL,
                [
                    "CREATE INDEX IF NOT EXISTS idx_orch_context_task_status "
                    "ON orch_context_messages(task_id, status)",
                    "CREATE INDEX IF NOT EXISTS idx_orch_context_run "
                    "ON orch_context_messages(run_id)",
                ],
            )
        conn.commit()
    finally:
        cursor.execute("PRAGMA foreign_keys=ON")
        conn.commit()

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        # 只告警不阻断：旧单列主键覆盖缺陷可能让历史 steer 上下文行的
        # (run_id, task_id) 在任务表已不存在；这些历史行保留展示。
        import logging

        logging.getLogger(__name__).warning(
            "v21 重建后存在历史外键悬空行（保留，不阻断）: %d 行，样例 %r",
            len(violations),
            violations[:5],
        )


__all__ = ["_v21_orch_tasks_composite_pk"]
