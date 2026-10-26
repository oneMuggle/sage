"""统一进化日志写入器（P0-1 自进化可观测性）。

此前 6 个进化任务各自维护一份近重复的 ``INSERT INTO evolution_log`` SQL，
字段口径不一致：部分任务写 before/after_state、部分不写；``tokens_used``
列从无写入点；耗时与量化指标一律缺失 —— 导致进化日志只有一段自由文本，
无法跨任务比对。

本模块收敛为单一写入入口，统一补齐:

* ``duration_ms``  —— 单调时钟耗时（毫秒整数）
* ``metrics_json`` —— 该次执行的量化指标（JSON 文本）

best-effort 语义沿用既有先例（``evolution._write_evolution_log``）：日志是
旁路，写入失败只 warning，绝不让进化任务整体失败 —— 日志缺失可接受，
进化中断不可接受。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# evolution_log.status 的取值域
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

# metrics_json 序列化上限：超长指标截断，避免单行日志膨胀到不可读
_MAX_METRICS_CHARS = 4000


def elapsed_ms(started_at: float) -> int:
    """单调时钟耗时（毫秒）。

    用 ``time.monotonic()`` 而非 ``time.time()``：后者会被系统时钟调整
    （NTP 校正、手动改表）影响，可能算出负数或虚高的耗时。

    Args:
        started_at: ``time.monotonic()`` 的起点快照

    Returns:
        毫秒整数
    """
    return int((time.monotonic() - started_at) * 1000)


def _serialize_metrics(metrics: Optional[Dict[str, Any]]) -> Optional[str]:
    """把指标字典序列化为 JSON 文本。

    非 dict（含 None）一律视为无指标 —— 指标是可选增强，脏数据不该
    让整条日志写入失败。
    """
    if not isinstance(metrics, dict) or not metrics:
        return None
    try:
        text = json.dumps(metrics, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        logger.warning("进化日志指标序列化失败，已丢弃 metrics: %s", exc)
        return None
    if len(text) > _MAX_METRICS_CHARS:
        text = text[:_MAX_METRICS_CHARS] + "…(truncated)"
    return text


def record_evolution_log(
    db,
    *,
    evolution_type: str,
    description: str,
    status: str = STATUS_SUCCESS,
    error_message: Optional[str] = None,
    before_state: Optional[str] = None,
    after_state: Optional[str] = None,
    trigger_type: str = "scheduled",
    trigger_condition: Optional[str] = None,
    duration_ms: Optional[int] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """写一条结构化进化日志。

    Args:
        db: Database 实例
        evolution_type: 进化任务类型（daily_summary / memory_pruning / ...）
        description: 人类可读描述
        status: success / failed / skipped
        error_message: 失败原因
        before_state: 变更前状态描述
        after_state: 变更后状态描述
        trigger_type: scheduled / manual / threshold
        trigger_condition: 触发条件描述
        duration_ms: 任务耗时（毫秒）
        metrics: 量化指标（JSON 序列化后存入 metrics_json）

    Returns:
        写入成功返回日志 id；失败返回 None（不抛异常）
    """
    metrics_json = _serialize_metrics(metrics)
    log_id = str(uuid.uuid4())
    now_ts = int(time.time())
    try:
        conn = db.get_connection()
        conn.execute(
            """
            INSERT INTO evolution_log
            (id, evolution_type, description, status, error_message,
             before_state, after_state, trigger_type, trigger_condition,
             duration_ms, metrics_json, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log_id,
                evolution_type,
                description,
                status,
                error_message,
                before_state,
                after_state,
                trigger_type,
                trigger_condition,
                duration_ms,
                metrics_json,
                now_ts,
                now_ts if status == STATUS_SUCCESS else None,
            ),
        )
        conn.commit()
        return log_id
    except Exception as exc:  # noqa: BLE001 — best-effort：日志失败不阻断进化任务
        logger.warning(
            "写入 evolution_log 失败 (evolution_type=%s, status=%s): %s",
            evolution_type,
            status,
            exc,
        )
        return None
