"""Usage/cost summary routes (M6 生态扩展)。

GET /api/v1/usage → {totals, by_model, today, cache_hit_rate}。
数据源是模块级内存 tracker (backend.services.usage_tracker.usage_tracker)。

GET /api/v1/usage/session/{session_id} → 该会话的持久化用量聚合
(L8, 批次 C): 来自 usage_events 表, 重启不丢。

GET /api/v1/usage/requests → 按时间倒序分页列出 usage_events 行
(L8 PR-B, 2026-09-09), 用作请求详情面板。

L8 PR-A (2026-09-09): summary 增 cache_hit_rate 派生指标;
session_summary 增 cache_read / cache_creation 拆分列与派生命中率。
L8 PR-B (2026-09-09): range 扩到 (today|7d|30d|total); 加 /requests 分页端点。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from backend.services.usage_tracker import usage_tracker

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("")
async def get_usage_summary(
    range: str = Query(  # noqa: A002 — 与 OpenAPI schema 字段名一致
        "today", pattern="^(today|7d|30d|total)$"
    ),
) -> Dict[str, Any]:
    """返回累计用量、按模型聚合、当日用量与缓存命中率。

    L8 PR-B: range 扩到 today/7d/30d/total; 7d/30d/total 走
    usage_daily_rollups 预聚合 (失败降级回内存态)。
    """
    return usage_tracker.summary_with_range(range)


@router.get("/requests")
async def list_usage_requests(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session_id: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """L8 PR-B (2026-09-09): 按 created_at DESC 分页列出 usage_events 行。

    - ``limit``: 1~500, 默认 50
    - ``offset``: ≥0
    - ``session_id``: 可选过滤

    返回 ``{items: [...], total: int, limit, offset}``。
    """
    try:
        from backend.data.database import _SQLITE_LOCK, get_database

        with _SQLITE_LOCK:
            conn = get_database().get_connection()
            where = ""
            params: tuple = ()
            if session_id is not None:
                where = " WHERE session_id = ?"
                params = (session_id,)
            total_row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM usage_events{where}", params
            ).fetchone()
            total = int(total_row["cnt"]) if total_row else 0
            rows = conn.execute(
                f"SELECT id, session_id, model, prompt_tokens, completion_tokens,"
                f" total_tokens, cached_tokens, cache_read_tokens,"
                f" cache_creation_tokens, estimated_cost_usd, created_at"
                f" FROM usage_events{where}"
                f" ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        items: List[Dict[str, Any]] = []
        for row in rows:
            created_at = int(row["created_at"] or 0)
            items.append(
                {
                    "id": str(row["id"] or ""),
                    "session_id": row["session_id"],
                    "model": str(row["model"] or ""),
                    "prompt_tokens": int(row["prompt_tokens"] or 0),
                    "completion_tokens": int(row["completion_tokens"] or 0),
                    "total_tokens": int(row["total_tokens"] or 0),
                    "cached_tokens": int(row["cached_tokens"] or 0),
                    "cache_read_tokens": int(row["cache_read_tokens"] or 0),
                    "cache_creation_tokens": int(row["cache_creation_tokens"] or 0),
                    "estimated_cost_usd": row["estimated_cost_usd"],
                    "created_at_ms": created_at,
                    "created_at_iso": _iso_from_ms(created_at),
                }
            )
        return {"items": items, "total": total, "limit": limit, "offset": offset}
    except Exception as exc:  # noqa: BLE001
        return {"items": [], "total": 0, "limit": limit, "offset": offset, "error": str(exc)}


def _iso_from_ms(ms: int) -> str:
    if ms <= 0:
        return ""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000.0))
    except Exception:  # noqa: BLE001
        return ""


@router.get("/session/{session_id}")
async def get_session_usage(session_id: str) -> Dict[str, Any]:
    """返回某会话的持久化用量聚合 (U14 头部徽章数据源)。

    L8 PR-A: 含 cache_read_tokens / cache_creation_tokens / cache_hit_rate。
    """
    return usage_tracker.session_summary(session_id)
