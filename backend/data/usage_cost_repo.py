"""M4.3b (2026-11-23): 编排金额账本（``usage_events`` 为唯一真相源）。

为什么金额不落在 ``orch_tasks``：该表主键是 ``task_id``，而计划任务编号
跨 run 复用（t1..tN）——同会话的第二个 run 会在 ``ON CONFLICT(task_id)``
上覆盖第一个 run 的行，金额随之串到别的 run 上。``usage_events`` 主键是
uuid，且 ``run_id`` 是显式列，按 run 聚合天然免疫该串扰。

口径（与前端渲染语义一一对应）：

  - 只统计**已知定价**行（``estimated_cost_usd IS NOT NULL``）；
  - 无已定价行 → ``None``（"未知定价" ≠ 免费，渲染层据此隐藏金额）；
  - conductor（主会话）调用的 ``task_id`` / ``run_id`` 均为空，不计入任何 run。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.data.database import get_database

logger = logging.getLogger(__name__)


class UsageCostRepository:
    """``usage_events`` 金额聚合（只读）。"""

    def __init__(self) -> None:
        self.db = get_database()

    def task_cost_usd(self, run_id: str, task_id: str) -> Optional[float]:
        """run 内某任务的已定价金额合计（USD 估算）。

        无已定价行 → ``None``（未知 ≠ 免费）；DB 故障 fail-open → ``None``。
        """
        if not run_id or not task_id:
            return None
        try:
            row = self.db.get_connection().execute(
                "SELECT COUNT(estimated_cost_usd) AS priced,"
                " COALESCE(SUM(estimated_cost_usd), 0) AS total"
                " FROM usage_events WHERE run_id = ? AND task_id = ?",
                (run_id, task_id),
            ).fetchone()
        except Exception as exc:  # noqa: BLE001 — fail-open：账本读不到就隐藏金额
            logger.warning("task_cost_usd 读取失败: %s", exc)
            return None
        if not row or not int(row["priced"] or 0):
            return None
        return round(float(row["total"] or 0.0), 8)

    def run_costs_usd(self, run_id: str) -> Dict[str, Any]:
        """run 级金额聚合。

        返回 ``{"total": float | None, "tasks": {task_id: amount}}``：

        - ``total`` —— run 内全部已定价行的合计；无已定价行 → ``None``；
        - ``tasks`` —— 只含**已定价**任务（未知定价的任务不出现 → 前端隐藏）。

        注：``total`` 统计 run 内**所有**已定价行（含极端情况下 task_id 为空的
        孤儿行），``tasks`` 只覆盖能归到任务上的行 —— 正常路径下两者相等
        （dispatcher 的 task_id 与 run_id 始终成对设置）。
        """
        empty: Dict[str, Any] = {"total": None, "tasks": {}}
        if not run_id:
            return empty
        try:
            conn = self.db.get_connection()
            rows = conn.execute(
                "SELECT task_id, SUM(estimated_cost_usd) AS total FROM usage_events"
                " WHERE run_id = ? AND task_id IS NOT NULL"
                " AND estimated_cost_usd IS NOT NULL GROUP BY task_id",
                (run_id,),
            ).fetchall()
            total_row = conn.execute(
                "SELECT COUNT(estimated_cost_usd) AS priced,"
                " COALESCE(SUM(estimated_cost_usd), 0) AS total"
                " FROM usage_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.warning("run_costs_usd 读取失败: %s", exc)
            return empty
        tasks = {row["task_id"]: round(float(row["total"] or 0.0), 8) for row in rows}
        total = (
            round(float(total_row["total"] or 0.0), 8)
            if total_row and int(total_row["priced"] or 0)
            else None
        )
        return {"total": total, "tasks": tasks}
