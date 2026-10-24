"""``OrchRunMetrics`` — 编排 run 级聚合查询（P119 Config Advisor Phase 2.1）。

为 ``diagnose_sage_config`` 工具提供"最近 N 次 run 的指标快照"，作为 LLM
给出配置优化建议的数据基础。聚合维度：

- completion: 成功/失败/取消计数
- failure_kind: 基于 ``orch_runs.final_summary`` 与 ``orch_tasks.error``
  的启发式归类（max_iterations_exceeded / timeout / rate_limit /
  context_window / other）
- tokens / latency_ms: 基于 ``orch_tasks.used_tokens`` / ``duration_ms``
- retries: 基于 ``orch_tasks.retry_count``

设计约束：
- 默认 ``limit=20``，性能可接受（orch_runs.created_at 已有索引）
- 不新建表 / 物化视图 —— 实时 join 查询，YAGNI
- 失败原因用字符串匹配归类，无需改 schema（未来量大了再固化枚举列）
- 全部 fail-safe：DB 不可用时返回空指标，不抛异常
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.data.database import get_database

logger = logging.getLogger(__name__)


def _empty_metrics() -> Dict[str, Any]:
    """DB 不可用或无任何 run 时的兜底结构。"""
    return {
        "window": {"from": None, "to": None, "run_count": 0},
        "completion": {"success": 0, "failed": 0, "cancelled": 0, "other": 0},
        "failure_kind": {},
        "tokens": {"mean_per_task": 0, "total": 0, "task_count_with_tokens": 0},
        "latency_ms": {"mean": 0, "p50": 0, "p95": 0},
        "retries": {"mean_per_task": 0.0, "tasks_with_retry_pct": 0.0},
    }


def _ms_to_iso(epoch_ms: Optional[int]) -> Optional[str]:
    if epoch_ms is None:
        return None
    try:
        return datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc).isoformat()
    except (OverflowError, ValueError, OSError):
        return None


def _percentile(values: List[int], p: float) -> int:
    """线性插值百分位（空列表返回 0）。"""
    if not values:
        return 0
    sorted_v = sorted(values)
    n = len(sorted_v)
    if n == 1:
        return sorted_v[0]
    rank = p / 100.0 * (n - 1)
    low = int(rank)
    high = min(low + 1, n - 1)
    frac = rank - low
    return int(sorted_v[low] + frac * (sorted_v[high] - sorted_v[low]))


def _classify_failure(error_text: Optional[str]) -> str:
    """基于错误文本的失败原因启发式归类。

    归类结果用作 ``failure_kind`` 字典的 key。未命中任何模式统一归类为
    ``"other"``。未来若误归类率高，可考虑固化为 DB schema 的枚举列。
    """
    if not error_text:
        return "other"
    t = error_text.lower()
    if "max_iterations" in t or "iteration limit" in t or ("iteration" in t and "exceed" in t):
        return "max_iterations_exceeded"
    if "timeout" in t or "timed out" in t:
        return "timeout"
    if "rate_limit" in t or "rate limit" in t or " 429" in t or t.startswith("429"):
        return "rate_limit"
    if "context" in t and ("window" in t or "length" in t or "token" in t):
        return "context_window"
    if "cancelled" in t or "canceled" in t:
        return "cancelled"
    return "other"


class OrchRunMetrics:
    """编排 run 聚合查询入口。"""

    @staticmethod
    def aggregate_recent(limit: int = 20) -> Dict[str, Any]:
        """聚合最近 ``limit`` 次 run 的关键指标。

        返回结构：

        .. code-block:: python

            {
              "window": {"from": "2026-10-20T...", "to": "2026-10-24T...", "run_count": 20},
              "completion": {"success": 14, "failed": 4, "cancelled": 1, "other": 1},
              "failure_kind": {"max_iterations_exceeded": 2, "timeout": 1},
              "tokens": {"mean_per_task": 45000, "total": 900000, "task_count_with_tokens": 20},
              "latency_ms": {"mean": 1200, "p50": 900, "p95": 8500},
              "retries": {"mean_per_task": 0.3, "tasks_with_retry_pct": 15.0},
            }
        """
        try:
            db = get_database()
            conn = db.get_connection()
            cursor = conn.cursor()
        except Exception as exc:  # noqa: BLE001 — fail-safe
            logger.debug("OrchRunMetrics: DB 不可用，返回空指标: %s", exc)
            return _empty_metrics()

        try:
            cursor.execute(
                """
                SELECT run_id, status, final_summary, created_at, dispatched_at
                FROM orch_runs
                ORDER BY COALESCE(dispatched_at, created_at) DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
        except Exception as exc:  # noqa: BLE001 — fail-safe
            logger.debug("OrchRunMetrics: 查询 orch_runs 失败: %s", exc)
            return _empty_metrics()

        if not rows:
            return _empty_metrics()

        run_ids = [r["run_id"] for r in rows]
        timestamps = [r["dispatched_at"] or r["created_at"] for r in rows]

        # completion 计数
        completion = {"success": 0, "failed": 0, "cancelled": 0, "other": 0}
        for r in rows:
            s = r["status"]
            if s == "completed":
                completion["success"] += 1
            elif s == "failed":
                completion["failed"] += 1
            elif s == "cancelled":
                completion["cancelled"] += 1
            else:
                completion["other"] += 1

        # failure_kind：failed run 的 final_summary 归类
        failure_kind: Dict[str, int] = {}
        for r in rows:
            if r["status"] != "failed":
                continue
            kind = _classify_failure(r["final_summary"])
            failure_kind[kind] = failure_kind.get(kind, 0) + 1

        # tasks 聚合：一次 SQL 拿所有 tasks
        placeholders = ",".join("?" for _ in run_ids)
        try:
            cursor.execute(
                "SELECT retry_count, error, used_tokens, duration_ms "
                "FROM orch_tasks "
                "WHERE run_id IN ({})".format(placeholders),
                run_ids,
            )
            task_rows = cursor.fetchall()
        except Exception as exc:  # noqa: BLE001 — fail-safe
            logger.debug("OrchRunMetrics: 查询 orch_tasks 失败: %s", exc)
            task_rows = []

        retry_counts = [t["retry_count"] for t in task_rows if t["retry_count"] is not None]
        tokens_list = [t["used_tokens"] for t in task_rows if t["used_tokens"]]
        latency_list = [t["duration_ms"] for t in task_rows if t["duration_ms"]]

        tasks_with_retry = sum(1 for r in retry_counts if r > 0)
        total_tasks = len(task_rows)

        return {
            "window": {
                "from": _ms_to_iso(min(timestamps)) if timestamps else None,
                "to": _ms_to_iso(max(timestamps)) if timestamps else None,
                "run_count": len(rows),
            },
            "completion": completion,
            "failure_kind": failure_kind,
            "tokens": {
                "mean_per_task": (
                    int(sum(tokens_list) / len(tokens_list)) if tokens_list else 0
                ),
                "total": sum(tokens_list),
                "task_count_with_tokens": len(tokens_list),
            },
            "latency_ms": {
                "mean": int(sum(latency_list) / len(latency_list)) if latency_list else 0,
                "p50": _percentile(latency_list, 50),
                "p95": _percentile(latency_list, 95),
            },
            "retries": {
                "mean_per_task": (
                    round(sum(retry_counts) / len(retry_counts), 2) if retry_counts else 0.0
                ),
                "tasks_with_retry_pct": (
                    round(tasks_with_retry / total_tasks * 100, 1) if total_tasks else 0.0
                ),
            },
        }


__all__ = ["OrchRunMetrics", "_classify_failure"]
