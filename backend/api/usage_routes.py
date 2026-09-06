"""Usage/cost summary routes (M6 生态扩展)。

GET /api/v1/usage → {totals, by_model, today}。数据源是模块级内存
tracker (backend.services.usage_tracker.usage_tracker), 无新 DB 表。

GET /api/v1/usage/session/{session_id} → 该会话的持久化用量聚合
(L8, 批次 C): 来自 usage_events 表, 重启不丢。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from backend.services.usage_tracker import usage_tracker

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("")
async def get_usage_summary() -> Dict[str, Any]:
    """返回累计用量、按模型聚合与当日用量。"""
    return usage_tracker.summary()


@router.get("/session/{session_id}")
async def get_session_usage(session_id: str) -> Dict[str, Any]:
    """返回某会话的持久化用量聚合 (U14 头部徽章数据源)。"""
    return usage_tracker.session_summary(session_id)
