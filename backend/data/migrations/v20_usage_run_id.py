# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""v20：usage_events.run_id 归因列 + 历史用量归因回填（M4.3b）。

- 旧库补 ``usage_events.run_id``（新库由 init_db 防御块先行 ALTER）；
- 把 ``task_id`` 非空但 ``run_id`` 为空的历史用量行按
  task_id + session + orch_tasks 起止时间窗（epoch 毫秒）反查 run_id。

金额不入库：``usage_events.estimated_cost_usd`` 本身即账本，金额一律
按 ``run_id`` 现场聚合（``backend/data/usage_cost_repo.py``）。

已知局限：``orch_tasks`` 以 task_id 为 PRIMARY KEY，计划 ID（t1..tN）跨
run 复用，同一 task 行只保存最后一次写入的 run_id —— 历史用量只能归属
到该行现存的 run_id。迁移不臆测更多，仅回填能由时间窗唯一确定归属的行。
迁移只作用于列值缺失的行，可安全重跑。
"""

from __future__ import annotations

from typing import Any

#: task_id 归因的 run 反查谓词（EXISTS 与 SET 子查询共用同一条件）。
#: 窗口两端都要求任务**已开始**（started_at 非空）—— 否则 never-started
#: 任务的下界会退化成 0，把整条会话时间线的用量都吸进来。
_TASK_WINDOW_MATCH = """
    FROM orch_tasks t
    JOIN orch_runs r ON r.run_id = t.run_id
    WHERE t.task_id = usage_events.task_id
      AND r.session_id = usage_events.session_id
      AND t.started_at IS NOT NULL
      AND usage_events.created_at >= t.started_at
      AND (t.finished_at IS NULL OR usage_events.created_at <= t.finished_at)
"""


def _v20_usage_events_run_id(conn: Any) -> None:
    """Backfill usage_events.run_id from the orch_tasks execution window."""
    table_names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "usage_events" not in table_names:
        # 极老库/精简 fixture 未建表 —— 交由 init_db DDL 负责。
        return

    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(usage_events)")
    usage_cols = {row[1] for row in cursor.fetchall()}
    if "run_id" not in usage_cols:
        cursor.execute("ALTER TABLE usage_events ADD COLUMN run_id TEXT")
        conn.commit()
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_usage_events_run
        ON usage_events(run_id, task_id, created_at)
        """
    )

    if "orch_tasks" in table_names and "orch_runs" in table_names:
        cursor.execute("PRAGMA table_info(orch_tasks)")
        task_cols = {row[1] for row in cursor.fetchall()}
        if "started_at" in task_cols and "finished_at" in task_cols:
            # 时间窗内唯一候选取最近终态的一行。
            cursor.execute(
                "UPDATE usage_events SET run_id = ("
                "SELECT t.run_id" + _TASK_WINDOW_MATCH + " ORDER BY t.finished_at DESC LIMIT 1"
                ") WHERE run_id IS NULL AND task_id IS NOT NULL"
                " AND session_id IS NOT NULL AND EXISTS (SELECT 1" + _TASK_WINDOW_MATCH + ")"
            )
    conn.commit()


__all__ = ["_v20_usage_events_run_id"]
