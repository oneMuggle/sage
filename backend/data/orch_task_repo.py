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
    revision: int = 0
    error: Optional[str] = None
    output_preview: Optional[str] = None
    blocked_by: Optional[List[str]] = None
    scratch_dir: Optional[str] = None
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    # RT24 (round32): 任务级用量/时长 —— 终态落库（dispatcher 写入）。
    used_tokens: Optional[int] = None
    duration_ms: Optional[int] = None
    parent_task_id: Optional[str] = None
    depth: int = 0
    # RT26 (round49): 重派来源任务 ID —— 历史任务树"重派"徽章。
    retry_of: Optional[str] = None


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
        used_tokens: Optional[int] = None,
        duration_ms: Optional[int] = None,
        parent_task_id: Optional[str] = None,
        depth: int = 0,
        retry_of: Optional[str] = None,
    ) -> None:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO orch_tasks (
                task_id, run_id, agent_id, goal, status, retry_count,
                error, output_preview, blocked_by, scratch_dir,
                started_at, finished_at, used_tokens, duration_ms,
                parent_task_id, depth, retry_of
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                status=excluded.status,
                retry_count=excluded.retry_count,
                error=excluded.error,
                output_preview=excluded.output_preview,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at,
                used_tokens=excluded.used_tokens,
                duration_ms=excluded.duration_ms,
                parent_task_id=excluded.parent_task_id,
                depth=excluded.depth,
                retry_of=excluded.retry_of
                -- revision is intentionally NOT touched here: it is an
                -- append-only audit counter bumped only by
                -- ``bump_revision_for_steer`` after a successful steer INSERT.
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
                used_tokens,
                duration_ms,
                parent_task_id,
                depth,
                retry_of,
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
        # RT24: 旧库可能尚未迁移出新列（init_db 前置保证一般已迁移，防御）。
        _cols = set(row.keys())
        return OrchTask(
            task_id=row["task_id"],
            run_id=row["run_id"],
            agent_id=row["agent_id"],
            goal=row["goal"],
            status=row["status"],
            retry_count=row["retry_count"],
            revision=row["revision"] if "revision" in _cols else 0,
            error=row["error"],
            output_preview=row["output_preview"],
            blocked_by=blocked_by,
            scratch_dir=row["scratch_dir"],
            used_tokens=row["used_tokens"] if "used_tokens" in _cols else None,
            duration_ms=row["duration_ms"] if "duration_ms" in _cols else None,
            parent_task_id=row["parent_task_id"] if "parent_task_id" in _cols else None,
            depth=row["depth"] if "depth" in _cols else 0,
            retry_of=row["retry_of"] if "retry_of" in _cols else None,
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    # ------------------------------------------------------------------ CAS

    def bump_revision_for_steer(self, task_id: str) -> bool:
        """Bump ``revision`` unconditionally after a successful steer INSERT.

        This makes the DB ``revision`` column an observable audit trail of
        successful steers. It is **not** the CAS authority — the in-memory
        ``SnapshotStore`` task revision is. The two counters count different
        things:
          - ``SnapshotStore.revision``: every task event (created/started/progress/...)
          - ``orch_tasks.revision``: successful steer count only

        Returns True iff a row was updated (task existed in the DB).
        """
        conn = self.db.get_connection()
        cursor = conn.execute(
            "UPDATE orch_tasks SET revision = revision + 1 WHERE task_id = ?",
            (task_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
