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
    # Wave 2 P1-5: 首次派发时间戳（epoch ms）。None = 未派发 → plan 仍可编辑；
    # 非 None = 已派发 → update_plan 返回 409（编辑生效窗口 = 首次派发前）。
    dispatched_at: Optional[int] = None
    # Wave 3 A9 (2026-08-14): resume 恢复流的原始请求（前端逐字重发）。
    original_request: Optional[str] = None


class OrchRunRepository:
    """SQLite-backed orch_runs CRUD（模式同 LaneRepository）。"""

    def __init__(self) -> None:
        self.db = get_database()

    def upsert(self, run: OrchRun) -> None:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO orch_runs (run_id, session_id, status, created_at, plan_json, final_summary, dispatched_at, original_request)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                session_id=excluded.session_id,
                status=excluded.status,
                plan_json=excluded.plan_json,
                final_summary=excluded.final_summary,
                dispatched_at=excluded.dispatched_at,
                original_request=excluded.original_request
            """,
            (
                run.run_id,
                run.session_id,
                run.status,
                run.created_at,
                run.plan_json,
                run.final_summary,
                run.dispatched_at,
                run.original_request,
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
            dispatched_at=row["dispatched_at"],
            original_request=row["original_request"],
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
                dispatched_at=row["dispatched_at"],
                original_request=row["original_request"],
            )
            for row in cursor.fetchall()
        ]

    def list_by_session(self, session_id: str, limit: int = 20) -> List[OrchRun]:
        """C1 (2026-09-09): 按会话列编排 run（新→旧），历史任务板恢复用。

        ``init_orch_run`` 落库时绑定 session_id；本查询把它暴露给
        ``GET /orch/runs?session_id=``（Wave 4 删除 list_runs 后唯一入口）。
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM orch_runs WHERE session_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        )
        return [
            OrchRun(
                run_id=row["run_id"],
                session_id=row["session_id"],
                status=row["status"],
                created_at=row["created_at"],
                plan_json=row["plan_json"],
                final_summary=row["final_summary"],
                dispatched_at=row["dispatched_at"],
                original_request=row["original_request"],
            )
            for row in cursor.fetchall()
        ]

    def mark_dispatched(self, run_id: str, dispatched_at: int) -> None:
        """首次派发标记：仅当 run 尚未派发时写入（幂等,first-dispatch-wins）。

        ChatDispatcher 在首次 dispatch 时调用;若 init_orch_run 尚未建行则静默跳过
        （降级,调用方已 try/except）。
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orch_runs SET dispatched_at = ? WHERE run_id = ? AND dispatched_at IS NULL",
            (dispatched_at, run_id),
        )
        conn.commit()

    def update_status(self, run_id: str, status: str) -> None:
        """run 状态更新（P2-9/A8 cancel 端点用）—— 只改 status，不碰其他字段。

        终态校验（cancelled/completed/failed 拒绝再次取消）由调用方负责。
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orch_runs SET status = ? WHERE run_id = ?",
            (status, run_id),
        )
        conn.commit()

    def finalize(self, run_id: str, status: str, final_summary: Optional[str]) -> None:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        # P0-4 (2026-08-20): 只闭环仍在 running 的 run —— 已被 cancelRun
        # 置 cancelled 的 run 不被 producer finally 的迟到 finalize 覆盖。
        cursor.execute(
            "UPDATE orch_runs SET status = ?, final_summary = ? "
            "WHERE run_id = ? AND status = 'running'",
            (status, final_summary, run_id),
        )
        conn.commit()

    def fail_stale_running_runs(self) -> int:
        """启动恢复（O6, 2026-09-08）：遗留 ``running`` 的编排 run 收口为 failed。

        与会话级 ``SessionRepository.recover_stale_run_states`` 同语义：
        后端被杀时 producer finally 的 finalize 没机会执行，orch_runs.status
        滞留 running。``run_id LIKE 'orch-%'`` 限定编排前缀，避开非编排
        写入行；已有 final_summary 的行不覆盖。

        仅启动期单线程调用（与 recover_stale_run_states 一致，不加锁）。

        Returns:
            被改写的行数（用于启动日志）；失败降级返回 0。
        """
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE orch_runs SET status = 'failed', "
                "final_summary = COALESCE(final_summary, ?) "
                "WHERE status = 'running' AND run_id LIKE 'orch-%'",
                ("应用重启，编排运行中断",),
            )
            conn.commit()
            return cursor.rowcount
        except Exception:  # noqa: BLE001 — 恢复失败不阻塞启动
            return 0
