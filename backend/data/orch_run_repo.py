"""``OrchRunRepository`` — 编排 run 持久化（Wave 2 P1-4）。

复用 LaneRepository 模式（``self.db = get_database()``）：每次构造从全局单例
拿连接，不在构造时接 db_path。orch_runs 表存编排 run 元数据 + 计划 JSON，
``resume`` 端点（Task 2）据此重建 ChatDispatcher。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from backend.data.database import get_database


@dataclass
class OrchRun:
    run_id: str
    session_id: str
    status: str  # running|completed|failed|cancelled
    created_at: int  # epoch ms
    plan_json: str
    final_summary: Optional[str] = None


class OrchRunRepository:
    """SQLite-backed orch_runs CRUD（模式同 LaneRepository）。"""

    def __init__(self) -> None:
        self.db = get_database()

    def upsert(self, run: OrchRun) -> None:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO orch_runs (run_id, session_id, status, created_at, plan_json, final_summary)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                session_id=excluded.session_id,
                status=excluded.status,
                plan_json=excluded.plan_json,
                final_summary=excluded.final_summary
            """,
            (
                run.run_id,
                run.session_id,
                run.status,
                run.created_at,
                run.plan_json,
                run.final_summary,
            ),
        )
        conn.commit()

    def get(self, run_id: str) -> Optional[OrchRun]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orch_runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return OrchRun(
            run_id=row["run_id"],
            session_id=row["session_id"],
            status=row["status"],
            created_at=row["created_at"],
            plan_json=row["plan_json"],
            final_summary=row["final_summary"],
        )

    def list(self, limit: int = 50, offset: int = 0) -> List[OrchRun]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM orch_runs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [
            OrchRun(
                run_id=row["run_id"],
                session_id=row["session_id"],
                status=row["status"],
                created_at=row["created_at"],
                plan_json=row["plan_json"],
                final_summary=row["final_summary"],
            )
            for row in cursor.fetchall()
        ]

    def finalize(self, run_id: str, status: str, final_summary: Optional[str]) -> None:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orch_runs SET status = ?, final_summary = ? WHERE run_id = ?",
            (status, final_summary, run_id),
        )
        conn.commit()
