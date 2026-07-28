"""Usage/cost summary routes (M6 生态扩展)。

GET /api/v1/usage → {totals, by_model, today}。数据源是模块级内存
tracker (backend.services.usage_tracker.usage_tracker), 无新 DB 表。
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
