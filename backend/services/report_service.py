"""报告存档服务（P3）—— 日报 / 周报的落库、列表与详情。

**与统计引擎的分工**：本模块只管「存」，不管「算」。双来源聚合与 LLM 生成
在 :mod:`backend.services.report_ai`；路由层先算后存，把生成时刻的正文与
统计快照一起写进 ``reports`` 表。

**快照语义**：``content`` / ``stats`` 一旦落库即冻结 —— 之后工作日志再改、
待办再变，历史报告也不回写。用户按周翻看时看到的是「当时得出的结论」。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.services.report_models import (
    MAX_CONTENT_CHARS,
    MAX_TITLE_CHARS,
    REPORT_TYPES,
    Report,
    row_to_report,
)

#: 单页最大条数 —— 与 worklog 同款，防止忘传 limit 时拉全表。
MAX_PAGE_SIZE = 100

#: 默认单页条数。
DEFAULT_PAGE_SIZE = 20


class ReportService:
    """报告的持久化与查询。与 ``WorklogService`` 同款：现取连接、用完 commit。"""

    def __init__(self, db: Any) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    @staticmethod
    def _normalize_day(value: str) -> str:
        """把 ``YYYY-MM-DD``（或更长）归一成日期部分；非法值抛 ``ValueError``。"""
        text = str(value or "").strip()
        if len(text) < 10:
            raise ValueError(f"invalid date: {value!r} (expected YYYY-MM-DD)")
        try:
            # 日期边界刻意用 naive datetime：报告时间窗按本地日历日切分，
            # 与 ``work_logs.created_at`` 的存储口径一致。
            datetime.strptime(text[:10], "%Y-%m-%d")  # noqa: DTZ007
        except ValueError as exc:
            raise ValueError(
                f"invalid date: {value!r} (expected YYYY-MM-DD)"
            ) from exc
        return text[:10]

    @staticmethod
    def _validate_type(report_type: str) -> str:
        if report_type not in REPORT_TYPES:
            raise ValueError(
                f"invalid report_type: {report_type!r} "
                f"(expected one of {', '.join(REPORT_TYPES)})"
            )
        return report_type

    @staticmethod
    def default_title(report_type: str, period_start: str, period_end: str) -> str:
        """用户没给标题时的默认名 —— ``日报 · 2026-11-27`` / ``周报 · A ~ B``。"""
        if report_type == "daily":
            return f"日报 · {period_start}"
        return f"周报 · {period_start} ~ {period_end}"

    def _build_filters(
        self, report_type: Optional[str] = None
    ) -> Tuple[str, List[Any]]:
        if not report_type:
            return "", []
        self._validate_type(report_type)
        return " WHERE report_type = ?", [report_type]

    # ------------------------------------------------------------------
    # 写操作
    # ------------------------------------------------------------------

    def create_report(
        self,
        *,
        title: Optional[str],
        report_type: str,
        period_start: str,
        period_end: str,
        content: str,
        stats: Optional[Dict[str, Any]] = None,
    ) -> Report:
        """存档一份报告。

        ``title`` 为空时按类型生成默认名；``period_start`` 必须不晚于
        ``period_end``（时间窗两端都含）。所有校验前置 —— 抛错时库没被动过。
        """
        rtype = self._validate_type(report_type)
        start = self._normalize_day(period_start)
        end = self._normalize_day(period_end)
        if start > end:
            raise ValueError("period_start must be <= period_end")

        text = (content or "").strip()
        if not text:
            raise ValueError("content must not be empty")
        text = text[:MAX_CONTENT_CHARS]

        title_text = (title or "").strip()[:MAX_TITLE_CHARS]
        if not title_text:
            title_text = self.default_title(rtype, start, end)

        stats_json = (
            json.dumps(stats, ensure_ascii=False, default=str)
            if isinstance(stats, dict)
            else None
        )
        now = self._now()
        conn = self.db.get_connection()
        cursor = conn.execute(
            """
            INSERT INTO reports (
                title, report_type, period_start, period_end,
                content, stats_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (title_text, rtype, start, end, text, stats_json, now, now),
        )
        conn.commit()
        created = self.get_report(int(cursor.lastrowid))
        if created is None:  # pragma: no cover — 刚插入的行不可能查不到
            raise RuntimeError("report row vanished right after insert")
        return created

    # ------------------------------------------------------------------
    # 读操作
    # ------------------------------------------------------------------

    def get_report(self, report_id: int) -> Optional[Report]:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM reports WHERE id = ?", (int(report_id),)
        ).fetchone()
        return row_to_report(row) if row is not None else None

    def list_reports(
        self,
        *,
        report_type: Optional[str] = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> List[Report]:
        """按创建时间倒序列出报告（分页）。"""
        where, params = self._build_filters(report_type)
        page = max(1, min(int(limit), MAX_PAGE_SIZE))
        offset = max(0, int(offset))
        conn = self.db.get_connection()
        rows = conn.execute(
            f"SELECT * FROM reports{where} "
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            params + [page, offset],
        ).fetchall()
        return [row_to_report(row) for row in rows]

    def count_reports(self, *, report_type: Optional[str] = None) -> int:
        """同一筛选条件下的总条数（分页用）。"""
        where, params = self._build_filters(report_type)
        conn = self.db.get_connection()
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM reports{where}", params
        ).fetchone()
        return int(row["total"]) if row else 0


# ----------------------------------------------------------------------
# 模块级单例（与 worklog_service 同款：装配根注入，路由层按需取用）
# ----------------------------------------------------------------------

_global_service: Optional[ReportService] = None


def get_report_service() -> Optional[ReportService]:
    """Return the process-wide report service, if initialised."""
    return _global_service


def init_report_service(db: Any) -> ReportService:
    """Initialise (and register) the process-wide report service."""
    global _global_service
    _global_service = ReportService(db)
    return _global_service
