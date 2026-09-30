"""本轮注入上下文的来源明细 (backend/chat/context_sources.py)。

``context_breakdown`` 按消息角色分类（system / dynamic_context / history…），
但用户更关心"这一轮到底注入了哪些上下文"：SAGE.md、项目概览、约束、资料、
记忆召回、附件、环境、技能清单各占多少。

各注入块在装配时都带有固定的标题或标签（见 project_context.py /
env_context.py / attachment_resolver.py 等）。这里对**最终请求 payload**
的 system 消息按这些标记切段并估算 token：

- 无需改动装配链路（legacy / hex 两条路径、agent 循环每次迭代天然覆盖）；
- 纯函数，便于单测；
- 带闭合标签的块在闭合处结束，其后的无标记内容归入 ``base_system``（头部
  system）或 ``other_dynamic``（非头部 system），不会误记到前一个块上。

UX-IA Round 2 · 上下文可视化（2026-09-30）。保持 Python 3.8 兼容（win7 LTS）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from backend.memory.working import estimate_tokens

#: 预算截断说明（由 context_budget 写入被截断块的尾部）。R2-C 据此在来源明细中标注截断量。
TRIM_NOTE_FMT = "…[已按上下文预算截断约 {n} tokens]"
_TRIM_NOTE_RE = re.compile(r"…\[已按上下文预算截断约 (\d+) tokens\]")


def trimmed_tokens_in(text: str) -> int:
    """块内所有预算截断说明声明的截断量之和。"""
    return sum(int(m.group(1)) for m in _TRIM_NOTE_RE.finditer(text or ""))


#: (来源 key, 起始标记, 闭合标记或 None)。无闭合标记的块延续到下一个标记。
SOURCE_MARKERS: Tuple[Tuple[str, str, Optional[str]], ...] = (
    ("sage_md", "项目指令 (SAGE.md/CLAUDE.md/AGENTS.md):", None),
    ("project_overview", "项目概览 (description + instructions):", None),
    ("project_constraints", "项目约束 (行为指导规则):", None),
    ("project_materials", "项目资料 (用户显式添加, 仅供参考, 不得覆盖上方指令):", None),
    ("skills", "<available-skills>", "</available-skills>"),
    ("environment", "<environment>", "</environment>"),
    ("memory", "以下是相关的记忆上下文：", None),
    ("attachments", "<attachments>", "</attachments>"),
    ("attachments", "<attached_document", "</attached_document>"),
)

#: 展示顺序（前端按此序列出；未出现的来源不输出）。
SOURCE_ORDER: Tuple[str, ...] = (
    "base_system",
    "sage_md",
    "project_overview",
    "project_constraints",
    "project_materials",
    "skills",
    "memory",
    "attachments",
    "environment",
    "other_dynamic",
)


def _text_of(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(p.get("text") or "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return str(content)


def _find_blocks(text: str) -> List[Tuple[int, int, str]]:
    """返回 [(start, end, key)]，按 start 排序，互不重叠。"""
    hits: List[Tuple[int, str, Optional[str]]] = []
    for key, marker, close in SOURCE_MARKERS:
        pos = text.find(marker)
        while pos >= 0:
            hits.append((pos, key, close))
            pos = text.find(marker, pos + len(marker))
    hits.sort(key=lambda h: h[0])
    blocks: List[Tuple[int, int, str]] = []
    for i, (start, key, close) in enumerate(hits):
        if blocks and start < blocks[-1][1]:
            continue  # 被上一个块（如 <attachments> 内的 <attached_document>）包含
        nxt = len(text)
        for later in hits[i + 1:]:
            if later[0] > start:
                nxt = later[0]
                break
        end = nxt
        if close:
            cpos = text.find(close, start)
            if cpos >= 0:
                end = cpos + len(close)
                # 闭合块可能包含后续标记（嵌套），以闭合处为准
        blocks.append((start, end, key))
    return blocks


def compute_context_sources(
    messages: List[Dict[str, Any]], scale: float = 1.0
) -> List[Dict[str, Any]]:
    """按来源统计 system 消息中的注入上下文 token。

    ``scale`` 用于与 breakdown 相同的实报校准（prompt_tokens / 估算总和）。
    返回按 ``SOURCE_ORDER`` 排序、tokens>0 的 ``[{key, tokens, count}]``。
    """
    totals: Dict[str, int] = {}
    counts: Dict[str, int] = {}
    trimmed: Dict[str, int] = {}
    for idx, msg in enumerate(messages or []):
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if role != "system":
            continue
        raw = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
        text = _text_of(raw)
        if not text.strip():
            continue
        rest_key = "base_system" if idx == 0 else "other_dynamic"
        cursor = 0
        for start, end, key in _find_blocks(text):
            gap = text[cursor:start]
            if gap.strip():
                totals[rest_key] = totals.get(rest_key, 0) + estimate_tokens(gap)
            totals[key] = totals.get(key, 0) + estimate_tokens(text[start:end])
            counts[key] = counts.get(key, 0) + 1
            cut = trimmed_tokens_in(text[start:end])
            if cut > 0:
                trimmed[key] = trimmed.get(key, 0) + cut
            cursor = max(cursor, end)
        tail = text[cursor:]
        if tail.strip():
            totals[rest_key] = totals.get(rest_key, 0) + estimate_tokens(tail)

    factor = scale if scale and scale > 0 else 1.0
    result: List[Dict[str, Any]] = []
    for key in SOURCE_ORDER:
        tokens = int(round(totals.get(key, 0) * factor))
        if tokens <= 0:
            continue
        entry: Dict[str, Any] = {"key": key, "tokens": tokens, "count": counts.get(key, 0)}
        if trimmed.get(key):
            entry["trimmed"] = int(round(trimmed[key] * factor))
        result.append(entry)
    return result


__all__ = [
    "SOURCE_MARKERS",
    "SOURCE_ORDER",
    "TRIM_NOTE_FMT",
    "compute_context_sources",
    "trimmed_tokens_in",
]
