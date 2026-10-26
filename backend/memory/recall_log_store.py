"""召回事件流持久化（P0-3：反馈信号落库 + A/B 变体终于可比较）。

背景
----
``backend/adapters/out/memory/adapter.py`` 的召回路径早已在做 A/B 权重实验
（A = ``[0.2, 0.8]`` 嵌入器基线 / B = ``[0.5, 0.5]`` 均权对照），用
``md5(query)`` 稳定选路 —— 但两个变体**从未被分别度量过**：``variant`` 没有
落到任何地方，也没有反馈信号可供对比。

本模块让 ``memory_recall_log`` 成为召回事件的事实源：

* 每次召回写一行（``query_hash`` / ``variant`` / ``weights`` / ``result_count``）
* 用户反馈通过 :func:`set_feedback` 回填 ``user_feedback`` 列
* :func:`aggregate_metrics` 给出总体指标与**按变体分组**的对比

写入是 **best-effort**：召回是热路径，写库失败只记日志，绝不阻塞返回。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: 反馈取值域（前端 up/down 两个按钮）
FEEDBACK_UP = "up"
FEEDBACK_DOWN = "down"
VALID_FEEDBACK = (FEEDBACK_UP, FEEDBACK_DOWN)

#: 正反馈取值（用于 satisfaction_rate 聚合）
_POSITIVE_FEEDBACK = frozenset({FEEDBACK_UP})


def query_hash(query: str) -> str:
    """query 的稳定 md5 指纹。

    与 ``adapter.py`` 选 A/B 变体**同口径** —— 那里取的是
    ``md5(query).hexdigest()[:8]`` 做二分，本函数返回同一个 md5 的完整
    hexdigest，前 8 位与那边一致，因此 hash 与 variant 永远对得上，
    实验可复现。
    """
    return hashlib.md5((query or "").encode("utf-8")).hexdigest()


def record_recall(
    db,
    *,
    query: str,
    variant: Optional[str] = None,
    weights: Optional[Sequence[float]] = None,
    result_count: int = 0,
    session_id: Optional[str] = None,
    log_id: Optional[str] = None,
) -> Optional[str]:
    """写一条召回事件。

    Args:
        db: Database 实例
        query: 原始 query（只存 hash，不存原文 —— 避免隐私内容落库）
        variant: A / B 变体标识
        weights: 本次实际使用的融合权重
        result_count: 本次返回的结果条数
        session_id: 会话 ID
        log_id: 预分配的日志 ID（便于调用方事后回填反馈）

    Returns:
        写入成功返回 log_id；失败返回 None（不抛异常）
    """
    if db is None:
        return None
    rid = log_id or str(uuid.uuid4())
    try:
        weights_json = None
        if weights is not None:
            try:
                weights_json = json.dumps(list(weights))
            except (TypeError, ValueError):
                weights_json = None
        conn = db.get_connection()
        conn.execute(
            """
            INSERT INTO memory_recall_log
            (id, query_hash, session_id, variant, weights_json,
             result_count, user_feedback, created_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                rid,
                query_hash(query),
                session_id,
                variant,
                weights_json,
                int(result_count),
                int(time.time()),
            ),
        )
        conn.commit()
        return rid
    except Exception as exc:  # noqa: BLE001 — best-effort：召回热路径不能被写库拖垮
        logger.warning("写入 memory_recall_log 失败: %s", exc)
        return None


def set_feedback(db, log_id: str, feedback: str) -> bool:
    """回填某次召回的用户反馈。返回是否更新成功。"""
    if db is None or not log_id:
        return False
    if feedback not in VALID_FEEDBACK:
        return False
    try:
        conn = db.get_connection()
        cursor = conn.execute(
            "UPDATE memory_recall_log SET user_feedback=? WHERE id=?",
            (feedback, log_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("回填召回反馈失败 (log_id=%s): %s", log_id, exc)
        return False


def _empty_bucket() -> Dict[str, Any]:
    return {
        "total": 0,
        "feedback_count": 0,
        "positive_count": 0,
        "negative_count": 0,
        "satisfaction_rate": 0.0,
        "feedback_satisfaction_rate": 0.0,
        "avg_result_count": 0.0,
    }


def _finalize(bucket: Dict[str, Any], result_sum: int) -> None:
    """把累计的计数换算成率值与均值。

    ``satisfaction_rate`` 的分母是**全部召回**（与 ``RecallEvaluator``
    内存路径的 ``positive / total`` 口径一致，两条路径可直接比较）；
    ``feedback_satisfaction_rate`` 的分母是**有反馈的召回**，
    回答"在给了反馈的那些次里，好评占多少"。
    """
    if bucket["total"]:
        bucket["satisfaction_rate"] = round(
            bucket["positive_count"] / bucket["total"], 4
        )
        bucket["avg_result_count"] = round(result_sum / bucket["total"], 4)
    if bucket["feedback_count"]:
        bucket["feedback_satisfaction_rate"] = round(
            bucket["positive_count"] / bucket["feedback_count"], 4
        )


def aggregate_metrics(db) -> Dict[str, Any]:
    """聚合召回指标：总体 + 按变体分组（A/B 对比）。

    ``by_variant`` 是本轮 P0-3 的核心产出 —— 它让那个早已存在、却从未被
    度量过的 A/B 实验第一次可比较。

    Returns:
        含 ``total_recalls`` / ``feedback_count`` / ``positive_count`` /
        ``negative_count`` / ``satisfaction_rate`` / ``avg_result_count`` /
        ``by_variant`` 的字典；``db`` 为 None 时返回空指标。
    """
    if db is None:
        return {
            "total_recalls": 0,
            "feedback_count": 0,
            "positive_count": 0,
            "negative_count": 0,
            "satisfaction_rate": 0.0,
            "feedback_satisfaction_rate": 0.0,
            "avg_result_count": 0.0,
            "by_variant": {},
        }

    overall = _empty_bucket()
    by_variant: Dict[str, Dict[str, Any]] = {}
    try:
        conn = db.get_connection()
        rows = conn.execute(
            "SELECT variant, result_count, user_feedback FROM memory_recall_log"
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("聚合召回指标失败: %s", exc)
        return {
            "total_recalls": 0,
            "feedback_count": 0,
            "positive_count": 0,
            "negative_count": 0,
            "satisfaction_rate": 0.0,
            "feedback_satisfaction_rate": 0.0,
            "avg_result_count": 0.0,
            "by_variant": {},
        }

    result_sum = 0
    variant_sums: Dict[str, int] = {}
    for row in rows:
        variant = row["variant"] or "unknown"
        feedback = row["user_feedback"]
        result_count = row["result_count"] or 0

        result_sum += result_count
        overall["total"] += 1
        bucket = by_variant.setdefault(variant, _empty_bucket())
        bucket["total"] += 1
        variant_sums[variant] = variant_sums.get(variant, 0) + result_count

        if feedback:
            overall["feedback_count"] += 1
            bucket["feedback_count"] += 1
            if feedback in _POSITIVE_FEEDBACK:
                overall["positive_count"] += 1
                bucket["positive_count"] += 1
            else:
                overall["negative_count"] += 1
                bucket["negative_count"] += 1

    _finalize(overall, result_sum)
    for variant, bucket in by_variant.items():
        _finalize(bucket, variant_sums.get(variant, 0))

    return {
        "total_recalls": overall["total"],
        "feedback_count": overall["feedback_count"],
        "positive_count": overall["positive_count"],
        "negative_count": overall["negative_count"],
        "satisfaction_rate": overall["satisfaction_rate"],
        "feedback_satisfaction_rate": overall["feedback_satisfaction_rate"],
        "avg_result_count": overall["avg_result_count"],
        "by_variant": by_variant,
    }


def list_recent(db, limit: int = 50) -> List[Dict[str, Any]]:
    """列出最近的召回事件（供前端「召回指标」视图展示）。"""
    if db is None:
        return []
    try:
        conn = db.get_connection()
        rows = conn.execute(
            "SELECT id, query_hash, session_id, variant, weights_json, "
            "result_count, user_feedback, created_at "
            "FROM memory_recall_log ORDER BY created_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("读取最近召回事件失败: %s", exc)
        return []
