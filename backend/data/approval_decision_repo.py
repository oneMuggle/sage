"""SQLite persistence for permission approval decisions (C2, 2026-09-09).

此前审批只在内存 ``ApprovalGate`` 里：应答后 future 释放、请求消散，
除 remember 规则外无任何持久痕迹。本 repo 记录每次决策（gui 批准/拒绝、
超时 default-deny、auto 模式自动放行），支撑事后审计与信任面回溯。

Schema ownership note: the authoritative DDL lives in
``backend/data/database.py`` (``approval_decisions``). This class assumes
the table exists and only performs CRUD.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

from backend.data.database import _SQLITE_LOCK, get_database


@dataclass(frozen=True)
class ApprovalDecision:
    """一条审批决策记录。"""

    id: str
    request_id: Optional[str]
    session_id: Optional[str]
    run_id: Optional[str]
    task_id: Optional[str]
    tool_name: str
    args_summary: Optional[str]
    risk: Optional[str]
    approved: bool
    answered_by: str  # gui | timeout | auto
    created_at: Optional[int]  # 请求创建时刻（epoch ms）；auto 决策无独立请求
    latency_ms: Optional[int]
    decided_at: int


class ApprovalDecisionRepository:
    """``approval_decisions`` 追加写 + 最近查询。"""

    def __init__(self) -> None:
        self.db = get_database()

    def append(
        self,
        *,
        tool_name: str,
        approved: bool,
        answered_by: str,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        run_id: Optional[str] = None,
        task_id: Optional[str] = None,
        args_summary: Optional[str] = None,
        risk: Optional[str] = None,
        created_at: Optional[int] = None,
        decided_at: Optional[int] = None,
    ) -> ApprovalDecision:
        """追加一条决策；返回落库行。失败向上抛，调用方（钩子）负责降级。"""
        now_ms = int(time.time() * 1000)
        decided = decided_at if decided_at is not None else now_ms
        latency = decided - created_at if created_at is not None else None
        decision = ApprovalDecision(
            id=f"apd-{uuid.uuid4().hex[:16]}",
            request_id=request_id,
            session_id=session_id,
            run_id=run_id,
            task_id=task_id,
            tool_name=tool_name,
            args_summary=args_summary,
            risk=risk,
            approved=bool(approved),
            answered_by=answered_by,
            created_at=created_at,
            latency_ms=latency,
            decided_at=decided,
        )
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            conn.execute(
                """
                INSERT INTO approval_decisions (
                    id, request_id, session_id, run_id, task_id, tool_name,
                    args_summary, risk, approved, answered_by, created_at,
                    latency_ms, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.id,
                    decision.request_id,
                    decision.session_id,
                    decision.run_id,
                    decision.task_id,
                    decision.tool_name,
                    decision.args_summary,
                    decision.risk,
                    1 if decision.approved else 0,
                    decision.answered_by,
                    decision.created_at,
                    decision.latency_ms,
                    decision.decided_at,
                ),
            )
            conn.commit()
        return decision

    def list(self, limit: int = 50) -> List[ApprovalDecision]:
        """最近决策（新→旧）。"""
        rows = self.db.get_connection().execute(
            "SELECT * FROM approval_decisions "
            "ORDER BY decided_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            ApprovalDecision(
                id=row["id"],
                request_id=row["request_id"],
                session_id=row["session_id"],
                run_id=row["run_id"],
                task_id=row["task_id"],
                tool_name=row["tool_name"],
                args_summary=row["args_summary"],
                risk=row["risk"],
                approved=bool(row["approved"]),
                answered_by=row["answered_by"],
                created_at=row["created_at"],
                latency_ms=row["latency_ms"],
                decided_at=row["decided_at"],
            )
            for row in rows
        ]


__all__ = ["ApprovalDecision", "ApprovalDecisionRepository"]
