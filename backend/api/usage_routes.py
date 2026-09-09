"""Usage/cost summary routes (M6 生态扩展)。

GET /api/v1/usage → {totals, by_model, today, cache_hit_rate}。
数据源是模块级内存 tracker (backend.services.usage_tracker.usage_tracker)。

GET /api/v1/usage/session/{session_id} → 该会话的持久化用量聚合
(L8, 批次 C): 来自 usage_events 表, 重启不丢。

GET /api/v1/usage/requests → 按时间倒序分页列出 usage_events 行
(L8 PR-B, 2026-09-09), 用作请求详情面板。

GET /api/v1/usage/trend → 按时间桶聚合的请求/Token/成本/命中率序列
(L8 PR-C, 2026-09-09), 用作趋势图。

GET /api/v1/usage/export.csv → CSV 导出 usage_events 行
(L8 PR-C, 2026-09-09), range 过滤 + session_id 可选。

L8 PR-A (2026-09-09): summary 增 cache_hit_rate 派生指标;
session_summary 增 cache_read / cache_creation 拆分列与派生命中率。
L8 PR-B (2026-09-09): range 扩到 (today|7d|30d|total); 加 /requests 分页端点。
L8 PR-C (2026-09-09): 加 /trend 时序 + /export.csv 导出; first_token_ms /
latency_ms 落库与透出。
"""

from __future__ import annotations

import csv
import io
import time
from datetime import datetime, timedelta, timezone  # datetime.UTC 是 Py 3.11+, sage-backend 跑 3.10
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

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


# ==================== L8 PR-C (2026-09-09): trend + CSV export ====================


_RANGE_TO_BUCKET = {
    "today": "hour",
    "7d": "day",
    "30d": "day",
    "total": "day",
}
_RANGE_TO_DAYS = {
    "today": 1,
    "7d": 7,
    "30d": 30,
    "total": 90,  # 截断 total 到 90 天, 避免 chart 时间轴无限长
}


@router.get("/trend")
async def get_usage_trend(
    range: str = Query(  # noqa: A002
        "7d", pattern="^(today|7d|30d|total)$"
    ),
    session_id: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """L8 PR-C (2026-09-09): 时间序列, 按桶聚合。

    返回 ``{range, bucket, series: [{ts, requests, prompt_tokens,
    completion_tokens, cost_usd, cache_hit_rate}]}``, ts 是桶起始 UTC
    ISO8601。bucket=today → hour (24 桶); 7d/30d/total → day。
    """
    try:
        from backend.data.database import _SQLITE_LOCK, get_database

        bucket = _RANGE_TO_BUCKET.get(range, "day")
        days = _RANGE_TO_DAYS.get(range, 7)
        cutoff_ms = int(
            (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000  # noqa: UP017 — datetime.UTC 是 Py 3.11+
        )
        with _SQLITE_LOCK:
            conn = get_database().get_connection()
            params: List[Any] = [cutoff_ms]
            where_session = ""
            if session_id is not None:
                where_session = " AND session_id = ?"
                params.append(session_id)
            if bucket == "hour":
                # strftime %Y-%m-%dT%H:00:00Z, 取 created_at 的整点起始
                fmt = "%Y-%m-%dT%H:00:00Z"
                trunc_expr = "strftime(?, created_at / 1000, 'unixepoch')"
                fmt_params: List[Any] = [fmt]
            else:
                fmt = "%Y-%m-%dT00:00:00Z"
                trunc_expr = "strftime(?, created_at / 1000, 'unixepoch')"
                fmt_params = [fmt]
            sql = (
                f"SELECT {trunc_expr} AS ts,"
                " COUNT(*) AS requests,"
                " COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,"
                " COALESCE(SUM(completion_tokens), 0) AS completion_tokens,"
                " COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,"
                " COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens,"
                " COALESCE(SUM(estimated_cost_usd), 0) AS cost_usd"
                " FROM usage_events WHERE created_at >= ?"
                f"{where_session}"
                f" GROUP BY ts ORDER BY ts ASC"
            )
            rows = conn.execute(sql, (*fmt_params, *params)).fetchall()
        series: List[Dict[str, Any]] = []
        for row in rows:
            prompt = int(row["prompt_tokens"] or 0)
            creation = int(row["cache_creation_tokens"] or 0)
            read = int(row["cache_read_tokens"] or 0)
            eligible = prompt + creation
            hit_rate = round(read / eligible, 4) if eligible > 0 else 0.0
            series.append(
                {
                    "ts": row["ts"] or "",
                    "requests": int(row["requests"] or 0),
                    "prompt_tokens": prompt,
                    "completion_tokens": int(row["completion_tokens"] or 0),
                    "cost_usd": round(float(row["cost_usd"] or 0), 6),
                    "cache_hit_rate": hit_rate,
                }
            )
        return {"range": range, "bucket": bucket, "series": series}
    except Exception as exc:  # noqa: BLE001
        return {
            "range": range,
            "bucket": _RANGE_TO_BUCKET.get(range, "day"),
            "series": [],
            "error": str(exc),
        }


@router.get("/export.csv", response_class=PlainTextResponse)
async def export_usage_csv(
    range: str = Query("total", pattern="^(today|7d|30d|total)$"),  # noqa: A002
    session_id: Optional[str] = Query(None),
) -> str:
    """L8 PR-C (2026-09-09): 导出 usage_events 为 CSV。

    表头固定, 列序: id, session_id, model, prompt_tokens, completion_tokens,
    total_tokens, cached_tokens, cache_read_tokens, cache_creation_tokens,
    estimated_cost_usd, first_token_ms, latency_ms, created_at_iso。

    范围由 ``range`` 限定 (默认 total)。``session_id`` 可选过滤。
    """
    try:
        from backend.data.database import _SQLITE_LOCK, get_database

        days = _RANGE_TO_DAYS.get(range, 90)
        cutoff_ms = int(
            (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000  # noqa: UP017 — datetime.UTC 是 Py 3.11+
        )
        with _SQLITE_LOCK:
            conn = get_database().get_connection()
            params: List[Any] = [cutoff_ms]
            where_session = ""
            if session_id is not None:
                where_session = " AND session_id = ?"
                params.append(session_id)
            rows = conn.execute(
                "SELECT id, session_id, model, prompt_tokens, completion_tokens,"
                " total_tokens, cached_tokens, cache_read_tokens,"
                " cache_creation_tokens, estimated_cost_usd, first_token_ms,"
                " latency_ms, created_at"
                f" FROM usage_events WHERE created_at >= ?{where_session}"
                " ORDER BY created_at DESC",
                params,
            ).fetchall()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "id",
                "session_id",
                "model",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "cached_tokens",
                "cache_read_tokens",
                "cache_creation_tokens",
                "estimated_cost_usd",
                "first_token_ms",
                "latency_ms",
                "created_at_iso",
            ]
        )
        for row in rows:
            created_ms = int(row["created_at"] or 0)
            writer.writerow(
                [
                    row["id"] or "",
                    row["session_id"] or "",
                    row["model"] or "",
                    int(row["prompt_tokens"] or 0),
                    int(row["completion_tokens"] or 0),
                    int(row["total_tokens"] or 0),
                    int(row["cached_tokens"] or 0),
                    int(row["cache_read_tokens"] or 0),
                    int(row["cache_creation_tokens"] or 0),
                    float(row["estimated_cost_usd"] or 0),
                    "" if row["first_token_ms"] is None else int(row["first_token_ms"]),
                    "" if row["latency_ms"] is None else int(row["latency_ms"]),
                    _iso_from_ms(created_ms),
                ]
            )
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        return f"# export failed: {exc}\n"
