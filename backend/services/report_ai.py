"""报告 AI 能力（P3）—— 工作日志 + 待办双来源 → 日报 / 周报 Markdown。

**双来源**：工作日志回答「做过了什么」，待办回答「要做什么 / 做完了什么」。
只看其中一边都会失真 —— 光看待办会漏掉没建过待办的临时工作，光看日志会
漏掉计划性任务与积压。

**降级策略**：LLM 未配置时 :func:`generate_with_fallback` 退到
:func:`render_template` —— 纯模板编译同一份上下文，报告永远出得来（只是
少了归纳与建议）。这也是「日报是辅助工具、不是聊天框」的产品底线：断网 /
没配 key 也不该让用户拿不到今天的工作记录。

单来源聚合口径与 :mod:`backend.services.worklog_service` 保持一致：只统计
``status='confirmed'`` 的工作日志；待办完成时间按 ``completed_at`` 落在窗内。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from backend.services.llm_endpoint import LLMNotConfiguredError, build_ai_client
from backend.services.worklog_models import WORKLOG_KINDS

logger = logging.getLogger(__name__)

#: 单次报告最多带入多少条工作日志（挡住整月数据撑爆提示词）。
MAX_WORKLOG_ITEMS = 80

#: 单类清单（完成 / 高优先级 / 逾期）最多带多少条待办标题。
MAX_TODO_TITLES = 20

#: kind 的中文标签 —— 模板与提示词共用。
KIND_LABELS = {
    "progress": "进展",
    "done": "完成",
    "blocker": "阻塞",
    "next": "下一步",
}

__all__ = [
    "LLMNotConfiguredError",
    "build_report_context",
    "digest_for_period",
    "render_template",
    "generate_report",
    "generate_with_fallback",
]


def _client() -> Any:
    """返回配置好的 LLM 客户端。

    实现与 ``todo_ai`` / ``worklog_ai`` 共用 :mod:`backend.services.llm_endpoint`
    的装配路径；这里保留薄封装作为测试打桩点。
    """
    return build_ai_client()


# ----------------------------------------------------------------------
# 时间窗工具（与 worklog_service 同口径：naive 本地 ISO8601）
# ----------------------------------------------------------------------


def _parse_day(value: str) -> datetime:
    text = str(value or "").strip()
    if len(text) < 10:
        raise ValueError(f"invalid date: {value!r} (expected YYYY-MM-DD)")
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d")  # noqa: DTZ007
    except ValueError as exc:
        raise ValueError(f"invalid date: {value!r} (expected YYYY-MM-DD)") from exc


def _day_lower_bound(value: str) -> str:
    """窗下界 —— 当天 00:00:00（含）。"""
    return _parse_day(value).isoformat()


def _day_upper_bound(value: str) -> str:
    """窗上界 —— 次日 00:00:00（开区间，含 ``period_end`` 当天整日）。"""
    return (_parse_day(value) + timedelta(days=1)).isoformat()


def _format_day(value: str) -> str:
    """``2026-11-27`` → ``11 月 27 日``；解析失败原样返回。"""
    try:
        date = _parse_day(value)
    except ValueError:
        return value
    return f"{date.month} 月 {date.day} 日"


def today_period() -> Tuple[str, str]:
    """今日窗口（日报默认值）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    return today, today


def week_period(days: int = 7) -> Tuple[str, str]:
    """近 N 天窗口（周报默认值，含今天）。"""
    now = datetime.now()
    start = (now - timedelta(days=max(1, days) - 1)).strftime("%Y-%m-%d")
    return start, now.strftime("%Y-%m-%d")


# ----------------------------------------------------------------------
# 单来源聚合
# ----------------------------------------------------------------------


def _worklog_section(
    worklog_service: Optional[Any], period_start: str, period_end: str
) -> Dict[str, Any]:
    """已确认工作日志的统计 + 明细（服务缺席时退化为空 section）。"""
    empty = {
        "total": 0,
        "by_kind": {kind: 0 for kind in WORKLOG_KINDS},
        "sessions": 0,
        "items": [],
    }
    if worklog_service is None:
        return empty
    summary = worklog_service.summarize(
        date_from=period_start, date_to=period_end
    )
    logs = worklog_service.list_worklogs(
        status="confirmed",
        date_from=period_start,
        date_to=period_end,
        limit=MAX_WORKLOG_ITEMS,
    )
    return {
        "total": summary.get("total", 0),
        "by_kind": summary.get("by_kind", empty["by_kind"]),
        "sessions": summary.get("sessions", 0),
        "items": [
            {
                "kind": log.kind,
                "content": log.content,
                "created_at": log.created_at,
            }
            for log in logs
        ],
    }


def _todo_titles(conn: Any, sql: str, params: List[Any]) -> List[str]:
    return [str(row["title"]) for row in conn.execute(sql, params).fetchall()]


def _todo_section(db: Any, period_start: str, period_end: str) -> Dict[str, Any]:
    """待办侧统计：窗内完成 / 高优先级积压 / 逾期 / 未完成总量。"""
    lower = _day_lower_bound(period_start)
    upper = _day_upper_bound(period_end)
    now_iso = datetime.now().isoformat()
    conn = db.get_connection()

    completed = _todo_titles(
        conn,
        "SELECT title FROM todos WHERE status = 'completed' "
        "AND completed_at IS NOT NULL "
        "AND completed_at >= ? AND completed_at < ? "
        "ORDER BY completed_at DESC LIMIT ?",
        [lower, upper, MAX_TODO_TITLES],
    )
    completed_row = conn.execute(
        "SELECT COUNT(*) AS n FROM todos WHERE status = 'completed' "
        "AND completed_at IS NOT NULL "
        "AND completed_at >= ? AND completed_at < ?",
        [lower, upper],
    ).fetchone()

    pending_high = _todo_titles(
        conn,
        "SELECT title FROM todos "
        "WHERE status IN ('pending', 'in_progress') AND priority = 'high' "
        "ORDER BY due_at ASC LIMIT ?",
        [MAX_TODO_TITLES],
    )
    overdue = _todo_titles(
        conn,
        "SELECT title FROM todos "
        "WHERE status IN ('pending', 'in_progress') "
        "AND due_at IS NOT NULL AND due_at < ? "
        "ORDER BY due_at ASC LIMIT ?",
        [now_iso, MAX_TODO_TITLES],
    )
    pending_row = conn.execute(
        "SELECT COUNT(*) AS n FROM todos WHERE status IN ('pending', 'in_progress')"
    ).fetchone()

    return {
        "completed": completed,
        "completed_count": int(completed_row["n"]) if completed_row else 0,
        "pending_high": pending_high,
        "overdue": overdue,
        "pending_count": int(pending_row["n"]) if pending_row else 0,
    }


# ----------------------------------------------------------------------
# 上下文 / 模板 / LLM
# ----------------------------------------------------------------------


def build_report_context(
    *,
    db: Any,
    worklog_service: Optional[Any],
    report_type: str,
    period_start: str,
    period_end: str,
) -> Dict[str, Any]:
    """聚合双来源为报告上下文（纯读，无副作用）。"""
    return {
        "report_type": report_type,
        "period_start": period_start,
        "period_end": period_end,
        "worklogs": _worklog_section(worklog_service, period_start, period_end),
        "todos": _todo_section(db, period_start, period_end),
    }


def digest_for_period(
    worklog_service: Optional[Any], *, period_start: str, period_end: str
) -> Dict[str, Any]:
    """给待办简报 / 周回顾用的工作日志 digest（P3.5 双来源升级）。"""
    return _worklog_section(worklog_service, period_start, period_end)


def _bullets(lines: List[str], empty_text: str = "（无）") -> str:
    if not lines:
        return f"- {empty_text}"
    return "\n".join(f"- {line}" for line in lines)


def render_template(context: Dict[str, Any]) -> str:
    """无 LLM 时的确定性 Markdown 模板（同一份上下文，永远可产出）。"""
    report_type = context.get("report_type", "daily")
    period_start = str(context.get("period_start", ""))
    period_end = str(context.get("period_end", ""))
    worklogs = context.get("worklogs") or {}
    todos = context.get("todos") or {}
    by_kind = worklogs.get("by_kind") or {}
    items = worklogs.get("items") or []

    kind_lines: Dict[str, List[str]] = {kind: [] for kind in WORKLOG_KINDS}
    for item in items:
        kind = item.get("kind") if item.get("kind") in kind_lines else "progress"
        content = str(item.get("content") or "").strip()
        if content:
            kind_lines[kind].append(content)

    is_daily = report_type == "daily"
    if is_daily:
        title = f"日报 · {_format_day(period_start)}"
        sections = [
            ("完成", _bullets(kind_lines["done"])),
            ("进展", _bullets(kind_lines["progress"])),
            ("阻塞与风险", _bullets(kind_lines["blocker"])),
            ("下一步", _bullets(kind_lines["next"])),
        ]
    else:
        title = f"周报 · {_format_day(period_start)} ~ {_format_day(period_end)}"
        suggestions: List[str] = []
        if todos.get("overdue"):
            suggestions.append(f"先清逾期：{'、'.join(todos['overdue'][:5])}")
        if todos.get("pending_high"):
            suggestions.append(f"跟进高优先级：{'、'.join(todos['pending_high'][:5])}")
        if not suggestions:
            suggestions.append("暂无积压，可安排一件长期推进的事")
        sections = [
            ("完成情况", _bullets(todos.get("completed") or [])),
            ("进展概览", _bullets(kind_lines["progress"] + kind_lines["done"])),
            ("阻塞与风险", _bullets(kind_lines["blocker"])),
            ("下周建议", _bullets(suggestions)),
        ]

    stats_lines = [
        f"工作日志 {int(worklogs.get('total', 0))} 条"
        f"（完成 {int(by_kind.get('done', 0))} / 进展 {int(by_kind.get('progress', 0))} /"
        f" 阻塞 {int(by_kind.get('blocker', 0))} / 下一步 {int(by_kind.get('next', 0))}），"
        f"覆盖 {int(worklogs.get('sessions', 0))} 个会话",
        f"待办完成 {int(todos.get('completed_count', 0))} 条；"
        f"未完成 {int(todos.get('pending_count', 0))} 条",
    ]

    lines = [f"# {title}", ""]
    for heading, body in sections:
        lines.extend([f"## {heading}", body, ""])
    lines.extend(["## 统计", _bullets(stats_lines), ""])
    return "\n".join(lines).strip()


def _prompt(context: Dict[str, Any]) -> str:
    report_type = context.get("report_type", "daily")
    is_daily = report_type == "daily"
    label = "日报" if is_daily else "周报"
    headings = (
        "「完成」「进展」「阻塞与风险」「下一步」"
        if is_daily
        else "「完成情况」「进展概览」「阻塞与风险」「下周建议」"
    )
    digest = json.dumps(
        {
            "period": {
                "start": context.get("period_start"),
                "end": context.get("period_end"),
            },
            "worklogs": context.get("worklogs"),
            "todos": context.get("todos"),
        },
        ensure_ascii=False,
        default=str,
    )
    return (
        f"你是个人效率教练。根据下面的双来源数据写一份中文{label}"
        f"（Markdown，用「## 」分小标题 {headings}，总长 ≤500 字，不要客套）。\n"
        "规则：只根据给定数据归纳，不要编造没有出现的事情；"
        "数据为空的小节写「（无）」。\n\n"
        f"数据（JSON）：\n{digest}\n"
    )


async def generate_report(context: Dict[str, Any]) -> str:
    """调用 LLM 生成报告 Markdown。

    LLM 未配置时抛 :class:`LLMNotConfiguredError`（由调用方决定是降级模板
    还是映射 503）；上游失败原样抛出。
    """
    client = _client()
    content = await client.complete(_prompt(context))
    return str(content or "").strip()


async def generate_with_fallback(context: Dict[str, Any]) -> Tuple[str, bool]:
    """生成报告并保证总有产出。

    Returns:
        ``(markdown, ai_generated)`` —— 未配置 LLM 或模型输出为空时退到
        模板，``ai_generated=False``；否则为模型文本，``ai_generated=True``。
    """
    try:
        text = await generate_report(context)
    except LLMNotConfiguredError:
        logger.info("report_ai: LLM 未配置，降级为模板报告")
        return render_template(context), False
    if not text.strip():
        logger.warning("report_ai: LLM 输出为空，降级为模板报告")
        return render_template(context), False
    return text, True
