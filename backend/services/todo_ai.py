"""待办 AI 能力（阶段 2）：对话→待办提炼 / 每日简报 / 周回顾。

复用 ``build_llm_client_from_settings().complete(prompt)``（与
complexity_classifier 同款装配路径）。LLM 未配置时抛
:class:`LLMNotConfiguredError`，路由层映射为 503；上游失败由路由映射 502。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.services.conversation_excerpt import load_conversation_excerpt
from backend.services.llm_endpoint import LLMNotConfiguredError, build_ai_client

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 10
# 会话摘录的预算常量与实现已抽到 ``conversation_excerpt``（P2，工作日志抽取
# 复用同一套预算），本模块只留候选解析与生成逻辑。
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)

__all__ = [
    "MAX_CANDIDATES",
    "LLMNotConfiguredError",
    "ExtractedTodoCandidate",
    "extract_todos",
    "generate_daily_brief",
    "generate_weekly_review",
]


class ExtractedTodoCandidate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due_at: Optional[str] = None
    priority: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


def _client() -> Any:
    """返回配置好的 LLM 客户端。

    实现已抽到 :mod:`backend.services.llm_endpoint`（P2，工作日志/报告抽取
    复用同一份装配路径与异常类型），这里保留薄封装作为测试打桩点。
    """
    return build_ai_client()


def _to_local_naive_iso(value: str) -> Optional[str]:
    """tz-aware → naive 本地；无法解析返回 None。"""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.isoformat()


def _load_conversation(session_id: str, message_ids: Optional[List[str]]) -> str:
    """把会话消息压成 ``[用户]/[助手]`` 摘录文本（有预算上限）。

    实现已迁到 :mod:`backend.services.conversation_excerpt`（P2 抽出，与工作
    日志抽取共用同一套预算常量），这里保留薄封装兼容既有调用方。
    """
    return load_conversation_excerpt(session_id, message_ids)


def _parse_candidates(raw: Any) -> List[Dict[str, Any]]:
    """解析 LLM 输出 → 清洗后的候选清单（坏项丢弃，上限 10）。"""
    if not isinstance(raw, str) or not raw.strip():
        return []
    text = raw.strip()
    fence = _CODE_FENCE_RE.search(text)
    if fence:
        text = fence.group(1)
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("todo_ai: LLM 输出不是合法 JSON")
        return []
    if not isinstance(data, list):
        return []

    candidates: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        due_at = item.get("due_at")
        due_at = _to_local_naive_iso(due_at) if isinstance(due_at, str) else None
        priority = item.get("priority")
        if priority not in ("high", "medium", "low"):
            priority = None
        raw_tags = item.get("tags")
        tags = (
            [str(t).strip()[:32] for t in raw_tags if str(t).strip()][:3]
            if isinstance(raw_tags, list)
            else []
        )
        candidates.append(
            {
                "title": title[:200],
                "due_at": due_at,
                "priority": priority,
                "tags": tags,
            }
        )
        if len(candidates) >= MAX_CANDIDATES:
            break
    return candidates


async def extract_todos(
    session_id: str, message_ids: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """从会话中提炼待办候选（不落库，由用户确认后再批量创建）。"""
    conversation = _load_conversation(session_id, message_ids)
    if not conversation.strip():
        return []
    client = _client()
    today = datetime.now().strftime("%Y-%m-%d")
    prompt = (
        "你是待办提炼助手。从下面的对话中提取用户需要亲自跟进的行动项"
        "（不要提取已完成的、纯寒暄的、或助手自己执行的任务）。只返回 JSON 数组，不要任何解释。\n\n"
        f"今天是 {today}。规则：\n"
        "- title 用动词开头、≤60 字，避免重复\n"
        "- due_at：对话中出现明确时间（如「周五前」「明天下午」）时换算成 "
        "ISO8601 本地时间（YYYY-MM-DDTHH:mm:ss），否则 null\n"
        "- priority：仅明确紧急/重要时给 high（可选 high/medium/low），否则 null\n"
        "- tags：0-3 个中文短标签\n"
        f"- 最多 {MAX_CANDIDATES} 条；没有可提炼的行动项则返回 []\n\n"
        '输出格式（仅 JSON 数组）：[{"title": "...", "due_at": null, '
        '"priority": null, "tags": []}]\n\n'
        f"对话记录：\n{conversation}\n"
    )
    raw = await client.complete(prompt)
    return _parse_candidates(raw)


def _todo_titles(items: Any, limit: int = 5) -> str:
    titles = []
    for item in (items or [])[:limit]:
        title = item.get("title") if isinstance(item, dict) else getattr(item, "title", None)
        if title:
            titles.append(str(title))
    return "、".join(titles) or "无"


def _worklog_lines(source: Dict[str, Any], limit: int = 6) -> str:
    """把工作日志摘要压成提示词里的一行。

    ``source`` 是启动摘要 / 统计字典，其中 ``worklogs`` 键由报告引擎
    （``report_ai.build_report_context``）填充 —— P3.5 的「双来源」入口。
    键缺席或为空时返回「无」，老调用方不受影响。
    """
    digest = source.get("worklogs") or {}
    if not isinstance(digest, dict):
        return "无"
    total = int(digest.get("total", 0) or 0)
    if total <= 0:
        return "无"
    by_kind = digest.get("by_kind") or {}
    breakdown = " / ".join(
        f"{label} {int(by_kind.get(key, 0) or 0)}"
        for key, label in (
            ("done", "完成"),
            ("progress", "进展"),
            ("blocker", "阻塞"),
            ("next", "下一步"),
        )
    )
    highlights: List[str] = []
    for item in (digest.get("items") or [])[:limit]:
        content = item.get("content") if isinstance(item, dict) else None
        if content:
            highlights.append(str(content))
    headline = f"{total} 条（{breakdown}）"
    if highlights:
        return f"{headline}：{'；'.join(highlights)}"
    return headline


async def generate_daily_brief(summary: Dict[str, Any]) -> str:
    """基于启动摘要生成「今日行动建议」（≤3 条短列表）。

    ``summary`` 里额外带了报告引擎填充的 ``worklogs`` 段（当天已确认的
    工作日志）—— 只看待办会漏掉「没建待办但确实干了」的工作。
    """
    client = _client()
    prompt = (
        "你是个人效率教练。根据下面的待办概况与工作日志，用中文给出今日行动建议"
        "（最多 3 条，每行以「• 」开头，总长 ≤120 字，不要客套和标题）。\n\n"
        f"逾期：{len(summary.get('overdue') or [])} 条（{_todo_titles(summary.get('overdue'))}）\n"
        f"今日到期：{len(summary.get('today') or [])} 条（{_todo_titles(summary.get('today'))}）\n"
        f"未来 7 天：{len(summary.get('upcoming') or [])} 条（{_todo_titles(summary.get('upcoming'))}）\n"
        f"高优先级：{len(summary.get('high_priority') or [])} 条（{_todo_titles(summary.get('high_priority'))}）\n"
        f"今日已完成：{summary.get('total_completed_today', 0)} 条\n"
        f"今日工作日志：{_worklog_lines(summary)}\n"
    )
    content = await client.complete(prompt)
    text = str(content or "").strip()
    return text or "• 今天暂无待办压力，可以安排一件长期推进的事。"


async def generate_weekly_review(
    stats: Dict[str, Any],
    completed_titles: List[str],
    pending_high: List[str],
    snoozed_titles: Optional[List[str]] = None,
) -> str:
    """生成周回顾（Markdown 短段落）。

    ``stats`` 里额外带了报告引擎填充的 ``worklogs`` 段（近 7 天已确认的
    工作日志）—— 待办说「要做什么」，工作日志说「实际做了什么」。
    """
    client = _client()
    completed_text = "、".join(completed_titles[:10]) or "无"
    pending_text = "、".join(pending_high[:10]) or "无"
    snoozed_text = "、".join((snoozed_titles or [])[:5]) or "无"
    prompt = (
        "你是个人效率教练。根据下面的待办数据与工作日志写一段中文周回顾"
        "（Markdown，包含「完成情况」「拖延提醒」「下周建议」三个小标题，总长 ≤300 字，不要客套）。\n\n"
        f"- 总数：{stats.get('total', 0)}，逾期：{stats.get('overdue', 0)}，"
        f"今日完成：{stats.get('completed_today', 0)}\n"
        f"- 状态分布：{stats.get('by_status', {})}\n"
        f"- 本周完成：{completed_text}\n"
        f"- 积压高优先级：{pending_text}\n"
        f"- 多次推迟的任务：{snoozed_text}\n"
        f"- 本周工作日志：{_worklog_lines(stats)}\n"
    )
    content = await client.complete(prompt)
    return str(content or "").strip() or "暂无足够数据生成周回顾。"
