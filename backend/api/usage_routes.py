"""Usage/cost summary routes (M6 生态扩展)。

GET /api/v1/usage → {totals, by_model, today, cache_hit_rate}。
数据源是模块级内存 tracker (backend.services.usage_tracker.usage_tracker)。

GET /api/v1/usage/session/{session_id} → 该会话的持久化用量聚合
(L8, 批次 C): 来自 usage_events 表, 重启不丢。

L8 PR-A (2026-09-09): summary 增 cache_hit_rate 派生指标;
session_summary 增 cache_read / cache_creation 拆分列与派生命中率。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Query

from backend.services.usage_tracker import usage_tracker

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("")
async def get_usage_summary(
    range: str = Query("today", pattern="^(today|total)$"),  # noqa: A002 — 与 OpenAPI schema 字段名一致
) -> Dict[str, Any]:
    """返回累计用量、按模型聚合、当日用量与缓存命中率。

    range=today (默认) → totals 复用 today 累计 (历史行为);
    range=total → totals 仍是累计 (当前等价, 为后续 PR-B 时间维度占位)。
    """
    summary = dict(usage_tracker.summary())
    summary["range"] = range
    return summary


@router.get("/session/{session_id}")
async def get_session_usage(session_id: str) -> Dict[str, Any]:
    """返回某会话的持久化用量聚合 (U14 头部徽章数据源)。

    L8 PR-A: 含 cache_read_tokens / cache_creation_tokens / cache_hit_rate。
    """
    return usage_tracker.session_summary(session_id)
