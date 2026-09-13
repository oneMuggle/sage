"""对标 S3（2026-09-13）：``@memory:`` / ``@wiki:`` / ``@skill:`` / ``@agent:`` 实体引用。

统一入口的一部分（竞品对标 §2.2）：在聊天输入框里直接引用记忆、Wiki 页面、
技能与智能体，而不必切页面。本模块把用户消息中的实体引用解析成一段
``<references>`` 上下文块，由路由层作为 trailing system 注入本轮请求。

语法（与 ``attachment_resolver`` 的 ``@path`` 共存，前缀区分）::

    @memory:火锅          → 记忆检索（episodic + semantic，按关键词）
    @wiki:量子纠缠        → 当前/最近 Wiki 项目内全文检索
    @skill:pdf-reader     → 技能描述 + 用法（精确名优先，其次前缀匹配）
    @agent:researcher     → 智能体简介 + 系统提示摘要

设计约束
--------
- 纯函数 + 惰性 import：不依赖 FastAPI；各数据源缺失/异常一律静默跳过，
  绝不阻断聊天。
- 每类引用最多 ``MAX_ITEMS_PER_REF`` 条、总块 ``MAX_BLOCK_CHARS`` 字符，
  避免把上下文撑爆。
- 引用文本保留在用户消息里（LLM 仍能看到 ``@memory:火锅`` 原文），只做
  "追加上下文"而不是改写用户输入。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

ENTITY_KINDS = ("memory", "wiki", "skill", "agent")

#: ``@kind:query`` —— query 到空白或句读标点（中英文逗号/句号/分号/问叹号/括号）为止。
_ENTITY_RE = re.compile(r"(?:^|(?<=\s))@(memory|wiki|skill|agent):([^\s，。,;；！？!?、（）()]+)")

MAX_ITEMS_PER_REF = 5
MAX_ITEM_CHARS = 600
MAX_BLOCK_CHARS = 6000


@dataclass
class EntityRef:
    kind: str
    query: str
    raw: str  # 原文（含 @kind: 前缀），供渲染标题


@dataclass
class ResolvedRef:
    ref: EntityRef
    items: List[str] = field(default_factory=list)
    note: Optional[str] = None  # 未命中/数据源不可用时的说明


def extract_entity_refs(text: str) -> List[EntityRef]:
    """扫描 ``@kind:query``；同一 (kind, query) 只保留首次。"""
    seen = set()
    refs: List[EntityRef] = []
    for m in _ENTITY_RE.finditer(text or ""):
        kind, query = m.group(1), m.group(2).strip().rstrip(".")
        if not query:
            continue
        key = (kind, query)
        if key in seen:
            continue
        seen.add(key)
        refs.append(EntityRef(kind=kind, query=query, raw=m.group(0)))
    return refs


def _clip(text: str, limit: int = MAX_ITEM_CHARS) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---- 各类解析器（惰性 import，失败静默） ---------------------------------


def _resolve_memory(query: str, session_id: Optional[str]) -> ResolvedRef:
    ref = EntityRef("memory", query, f"@memory:{query}")
    try:
        from backend.memory import get_memory_manager

        mm = get_memory_manager()
        rows = mm.search_memories(query, memory_type=None, limit=MAX_ITEMS_PER_REF, session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("@memory resolve skipped: %s", exc)
        return ResolvedRef(ref, note="记忆系统不可用")
    items = []
    for r in rows or []:
        content = r.get("content") or r.get("summary") or ""
        if not content:
            continue
        mtype = r.get("memory_type") or r.get("source") or "memory"
        items.append(f"[{mtype}] {_clip(str(content))}")
    return ResolvedRef(ref, items=items, note=None if items else "没有匹配的记忆")


def _wiki_project_root() -> Optional[Path]:
    """最近打开的 Wiki 项目（recent-projects 首项）；没有则 None。"""
    try:
        from backend.storage.recent_projects import load_recent

        recent = load_recent()
        if not recent:
            return None
        root = Path(recent[0].path)
        return root if root.is_dir() else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("@wiki project lookup skipped: %s", exc)
        return None


def _resolve_wiki(query: str, _session_id: Optional[str]) -> ResolvedRef:
    ref = EntityRef("wiki", query, f"@wiki:{query}")
    root = _wiki_project_root()
    if root is None:
        return ResolvedRef(ref, note="尚未打开任何 Wiki 项目")
    try:
        from backend.wiki.search import search_wiki

        resp = search_wiki(root, query, limit=MAX_ITEMS_PER_REF)
        results = list(getattr(resp, "results", []) or [])
    except Exception as exc:  # noqa: BLE001
        logger.debug("@wiki resolve skipped: %s", exc)
        return ResolvedRef(ref, note="Wiki 检索失败")
    items = [f"{r.title} ({r.path}): {_clip(r.snippet)}" for r in results if getattr(r, "title", None)]
    return ResolvedRef(ref, items=items, note=None if items else f"Wiki「{root.name}」中没有匹配页面")


def _resolve_skill(query: str, _session_id: Optional[str]) -> ResolvedRef:
    ref = EntityRef("skill", query, f"@skill:{query}")
    try:
        from backend.api.legacy_routes import _get_skill_adapter

        adapter = _get_skill_adapter()
        skills = list(adapter.list_skills_extended())
    except Exception as exc:  # noqa: BLE001
        logger.debug("@skill resolve skipped: %s", exc)
        return ResolvedRef(ref, note="技能系统不可用")
    q = query.lower().lstrip("/")
    exact = [s for s in skills if str(s.get("name", "")).lower() == q]
    fuzzy = [s for s in skills if q in str(s.get("name", "")).lower() and s not in exact]
    items = []
    for s in (exact + fuzzy)[:MAX_ITEMS_PER_REF]:
        name = s.get("name", "")
        desc = s.get("description") or ""
        enabled = adapter.is_enabled(name) if hasattr(adapter, "is_enabled") else True
        state = "" if enabled else "（已停用）"
        items.append(f"/{name}{state}: {_clip(str(desc), 300)}")
    return ResolvedRef(ref, items=items, note=None if items else "没有匹配的技能")


def _resolve_agent(query: str, _session_id: Optional[str]) -> ResolvedRef:
    ref = EntityRef("agent", query, f"@agent:{query}")
    try:
        from backend.data.agent_repo import AgentRepository

        agents = AgentRepository().list_all()
    except Exception as exc:  # noqa: BLE001
        logger.debug("@agent resolve skipped: %s", exc)
        return ResolvedRef(ref, note="智能体列表不可用")
    q = query.lower()

    def _hit(a: Dict) -> bool:
        return q in str(a.get("id", "")).lower() or q in str(a.get("name", "")).lower()

    items = []
    for a in [a for a in agents if _hit(a)][:MAX_ITEMS_PER_REF]:
        name = a.get("name") or a.get("id")
        desc = a.get("description") or ""
        prompt = a.get("system_prompt") or ""
        tools = a.get("tools") or []
        tool_str = f"；工具: {', '.join(map(str, tools[:8]))}" if isinstance(tools, list) and tools else ""
        items.append(f"{name} ({a.get('id')}): {_clip(str(desc), 200)}{tool_str}；提示词摘要: {_clip(str(prompt), 240)}")
    return ResolvedRef(ref, items=items, note=None if items else "没有匹配的智能体")


_RESOLVERS: Dict[str, Callable[[str, Optional[str]], ResolvedRef]] = {
    "memory": _resolve_memory,
    "wiki": _resolve_wiki,
    "skill": _resolve_skill,
    "agent": _resolve_agent,
}


def resolve_entity_refs(refs: List[EntityRef], session_id: Optional[str] = None) -> List[ResolvedRef]:
    out: List[ResolvedRef] = []
    for ref in refs:
        resolver = _RESOLVERS.get(ref.kind)
        if resolver is None:
            continue
        try:
            out.append(resolver(ref.query, session_id))
        except Exception as exc:  # noqa: BLE001 — 单个引用失败不影响其它
            logger.debug("entity ref resolve failed (%s): %s", ref.raw, exc)
            out.append(ResolvedRef(ref, note="解析失败"))
    return out


_KIND_TITLE = {"memory": "记忆", "wiki": "Wiki", "skill": "技能", "agent": "智能体"}


def render_references_block(resolved: List[ResolvedRef]) -> str:
    """渲染为 ``<references>`` 块；无引用返回空串。总长受 MAX_BLOCK_CHARS 约束。"""
    if not resolved:
        return ""
    parts = [
        "<references>",
        "用户在消息中用 @memory: / @wiki: / @skill: / @agent: 引用了以下内容，"
        "请把它们作为本轮回答的上下文：",
    ]
    used = sum(len(p) + 1 for p in parts)
    for r in resolved:
        title = f"=== {_KIND_TITLE.get(r.ref.kind, r.ref.kind)}: {r.ref.query} ==="
        lines = [title]
        if r.items:
            lines.extend(f"- {it}" for it in r.items)
        else:
            lines.append(f"- （{r.note or '无结果'}）")
        section = "\n".join(lines)
        cost = len(section) + 1
        if used + cost > MAX_BLOCK_CHARS:
            parts.append(f"=== {_KIND_TITLE.get(r.ref.kind, r.ref.kind)}: {r.ref.query} ===\n- （已省略：上下文预算不足）")
            continue
        parts.append(section)
        used += cost
    parts.append("</references>")
    return "\n".join(parts)


def process(text: str, session_id: Optional[str] = None) -> str:
    """路由层一键调用：返回 references 块（可能为空串）。"""
    refs = extract_entity_refs(text)
    if not refs:
        return ""
    return render_references_block(resolve_entity_refs(refs, session_id))


__all__ = [
    "ENTITY_KINDS",
    "EntityRef",
    "ResolvedRef",
    "extract_entity_refs",
    "process",
    "render_references_block",
    "resolve_entity_refs",
]
