"""报告数据模型 —— ``reports`` 行 ↔ ``Report`` 模型的映射（P3）。

与 :mod:`backend.services.worklog_models` 同款结构：模型定义与行映射各自
独立成模块，服务层只留业务逻辑。

**报告是快照，不是视图**：``content`` 与 ``stats`` 在生成时刻冻结，之后工作
日志再改也不回写历史报告 —— 复盘要的是当时的结论，不是随数据漂移的视图。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from pydantic import BaseModel

#: ``reports`` columns that map onto :class:`Report`, in model-field order.
#: ``stats_json`` 不在其中 —— 它由 :func:`row_to_report` 解码成 ``stats``。
REPORT_MODEL_FIELDS = (
    "id",
    "title",
    "report_type",
    "period_start",
    "period_end",
    "content",
    "created_at",
    "updated_at",
)

#: 报告类型白名单 —— 日报 / 周报。
REPORT_TYPES = ("daily", "weekly")

#: 正文最长字符数 —— 挡住异常膨胀的模型输出撑爆单行。
MAX_CONTENT_CHARS = 20000

#: 标题最长字符数。
MAX_TITLE_CHARS = 200


class Report(BaseModel):
    """一份已存档的报告（日报 / 周报）。"""

    id: int
    title: str
    report_type: str  # daily / weekly
    period_start: str  # YYYY-MM-DD（含）
    period_end: str  # YYYY-MM-DD（含）
    content: str  # Markdown 正文
    stats: Optional[Dict[str, Any]] = None  # 生成时刻的统计快照
    created_at: str
    updated_at: str


def row_to_report(row) -> Report:
    """Convert a ``reports`` row to a :class:`Report` model.

    ``stats_json`` 解码失败（历史脏数据 / 手工改库）降级为 ``None``，不让列表
    渲染整体崩掉 —— 与 ``row_to_worklog`` 的降级策略一致。
    """
    keys = set(row.keys())
    data = {name: row[name] for name in REPORT_MODEL_FIELDS if name in keys}
    raw_stats = row["stats_json"] if "stats_json" in keys else None
    stats: Optional[Dict[str, Any]] = None
    if raw_stats:
        try:
            decoded = json.loads(raw_stats)
        except (TypeError, ValueError):
            decoded = None
        if isinstance(decoded, dict):
            stats = decoded
    data["stats"] = stats
    return Report(**data)
