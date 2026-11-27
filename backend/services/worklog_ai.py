"""工作日志 AI 能力（P2）：对话 → 工作日志候选。

与 :mod:`backend.services.todo_ai` 同款结构 —— 从会话里「读出」条目，但**不落
库**：本模块只产出候选清单，由用户在收件箱里逐条确认（确认后才进日报统计）。

抽取路径的复用关系::

    conversation_excerpt ──▶ 本模块的提示词输入
    llm_endpoint         ──▶ 本模块的 LLM 客户端与异常类型

候选的 ``kind`` 取自 :data:`backend.services.worklog_models.WORKLOG_KINDS`
（进展 / 完成 / 阻塞 / 下一步）—— 与 ``work_logs.kind`` 列同一套白名单。
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
from backend.services.worklog_models import WORKLOG_KINDS

logger = logging.getLogger(__name__)

#: 单次抽取最多给多少条候选（与 todo_ai 对齐）。
MAX_CANDIDATES = 10

#: 候选正文最长字符数 —— 挡住模型把整段对话原样吐回来。
MAX_CONTENT_CHARS = 500

#: 进展描述 / 阻塞描述的最长字符数。
MAX_DETAIL_CHARS = 500

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)

__all__ = [
    "MAX_CANDIDATES",
    "LLMNotConfiguredError",
    "WorklogCandidate",
    "extract_worklogs",
]


class WorklogCandidate(BaseModel):
    """一条待确认的工作日志候选。

    ``kind`` 决定这条记录在日报里怎么被归类：``progress``（进展）、
    ``done``（已完成）、``blocker``（阻塞）、``next``（下一步）。
    """

    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    kind: str = "progress"
    progress_text: Optional[str] = None
    blocker: Optional[str] = None


def _client() -> Any:
    """返回配置好的 LLM 客户端。

    实现已抽到 :mod:`backend.services.llm_endpoint`（P2，待办 / 工作日志 /
    报告三处共用），这里保留薄封装作为测试打桩点。
    """
    return build_ai_client()


def _load_conversation(session_id: str, message_ids: Optional[List[str]]) -> str:
    """把会话消息压成 ``[用户]/[助手]`` 摘录文本（有预算上限）。"""
    return load_conversation_excerpt(session_id, message_ids)


def _clean_detail(value: Any) -> Optional[str]:
    """把模型给的进展 / 阻塞描述压成一段干净文本；空值返回 ``None``。"""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:MAX_DETAIL_CHARS]


def _parse_candidates(raw: Any) -> List[Dict[str, Any]]:
    """解析 LLM 输出 → 清洗后的候选清单（坏项丢弃，上限 10）。

    解析路径与 ``todo_ai._parse_candidates`` 一致：剥 code fence → 取最外层
    JSON 数组 → 逐项校验。**枚举外的 ``kind`` 一律降级为 ``progress``**，不
    丢弃整条 —— 抽取到的内容本身有价值，只是分类不可信。
    """
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
        logger.warning("worklog_ai: LLM 输出不是合法 JSON")
        return []
    if not isinstance(data, list):
        return []

    candidates: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str):
            continue
        content = content.strip()
        if not content:
            continue
        kind = item.get("kind")
        if kind not in WORKLOG_KINDS:
            kind = "progress"
        candidates.append(
            {
                "content": content[:MAX_CONTENT_CHARS],
                "kind": kind,
                "progress_text": _clean_detail(item.get("progress_text")),
                "blocker": _clean_detail(item.get("blocker")),
            }
        )
        if len(candidates) >= MAX_CANDIDATES:
            break
    return candidates


async def extract_worklogs(
    session_id: str, message_ids: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """从会话中提炼工作日志候选（**不落库**，由用户确认后再逐条入库）。

    Returns:
        候选 dict 列表，每条含 ``content`` / ``kind`` / ``progress_text`` /
        ``blocker``；会话为空时返回空列表，模型未配置时抛
        :class:`LLMNotConfiguredError`（路由层映射 503）。
    """
    conversation = _load_conversation(session_id, message_ids)
    if not conversation.strip():
        return []
    client = _client()
    today = datetime.now().strftime("%Y-%m-%d")
    prompt = (
        "你是工作日志提炼助手。从下面的对话中提取用户**实际做过的事**、"
        "遇到的阻塞、以及明确说出口的下一步计划"
        "（不要提取寒暄、闲聊、纯提问、以及助手自己执行的任务）。"
        "只返回 JSON 数组，不要任何解释。\n\n"
        f"今天是 {today}。规则：\n"
        "- content：一句话陈述这件事，用中文，≤80 字，避免重复\n"
        "- kind：只能是 progress（进展）、done（已完成）、blocker（阻塞）、"
        "next（下一步）四个值之一；判断不了就用 progress\n"
        "- progress_text：可选，补充具体进展细节；没有则 null\n"
        "- blocker：仅 kind=blocker 时填写，写清卡在哪里；否则 null\n"
        f"- 最多 {MAX_CANDIDATES} 条；没有可提炼内容则返回 []\n\n"
        '输出格式（仅 JSON 数组）：[{"content": "...", "kind": "progress", '
        '"progress_text": null, "blocker": null}]\n\n'
        f"对话记录：\n{conversation}\n"
    )
    raw = await client.complete(prompt)
    return _parse_candidates(raw)
