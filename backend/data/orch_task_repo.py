"""``OrchTaskRepository`` — 编排 task 状态持久化（Wave 2 P1-4）。

与 ``OrchRunRepository`` 同模式（``self.db = get_database()``）。orch_tasks
表存每个 task 的实时状态（status / retry_count / blocked_by / scratch_dir），
由 ChatDispatcher 每次 ``_emit_task_status`` 时 upsert 覆盖。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, List, Optional

from backend.data.database import get_database


@dataclass
class OrchTask:
    task_id: str
    run_id: str
    agent_id: str
    goal: str
    status: str = "queued"  # queued|running|done|failed
    retry_count: int = 0
    error: Optional[str] = None
    output_preview: Optional[str] = None
    blocked_by: Optional[List[str]] = None
    scratch_dir: Optional[str] = None
    started_at: Optional[int] = None
    finished_at: Optional[int] = None


class OrchTaskRepository:
    """SQLite-backed orch_tasks CRUD。"""

    def __init__(self) -> None:
        self.db = get_database()

    def upsert_state(
        self,
        task_id: str,
        run_id: str,
        agent_id: str,
        goal: str,
        status: str,
        retry_count: int = 0,
        error: Optional[str] = None,
        output_preview: Optional[str] = None,
        blocked_by: Optional[List[str]] = None,
        scratch_dir: Optional[str] = None,
        started_at: Optional[int] = None,
        finished_at: Optional[int] = None,
    ) -> None:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO orch_tasks (
                task_id, run_id, agent_id, goal, status, retry_count,
                error, output_preview, blocked_by, scratch_dir,
                started_at, finished_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                status=excluded.status,
                retry_count=excluded.retry_count,
                error=excluded.error,
                output_preview=excluded.output_preview,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at
            """,
            (
                task_id,
                run_id,
                agent_id,
                goal,
                status,
                retry_count,
                error,
                output_preview,
                json.dumps(blocked_by) if blocked_by is not None else None,
                scratch_dir,
                started_at,
                finished_at,
            ),
        )
        conn.commit()

    def get(self, task_id: str) -> Optional[OrchTask]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orch_tasks WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        return self._row_to_task(row) if row else None

    def list_by_run(self, run_id: str) -> List[OrchTask]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM orch_tasks WHERE run_id = ? ORDER BY task_id ASC",
            (run_id,),
        )
        return [self._row_to_task(row) for row in cursor.fetchall()]

    def _row_to_task(self, row: Any) -> OrchTask:
        blocked_by = json.loads(row["blocked_by"]) if row["blocked_by"] else None
        return OrchTask(
            task_id=row["task_id"],
            run_id=row["run_id"],
            agent_id=row["agent_id"],
            goal=row["goal"],
            status=row["status"],
            retry_count=row["retry_count"],
            error=row["error"],
            output_preview=row["output_preview"],
            blocked_by=blocked_by,
            scratch_dir=row["scratch_dir"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )
