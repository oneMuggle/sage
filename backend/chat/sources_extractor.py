"""统一「参考来源」提取（Round 58）：把工具命中解析成可核对的来源条目。

回答下方的引用区块需要列出本轮 LLM 实际检索到的记忆/知识库/网页/工具
命中。检索注入发生在两条互不相干的管道：动态上下文（记忆/附件 RAG，
producer 自己发 ``memory_used`` / ``attachment_rag_used``）与 ReAct 工具
循环（web_search / web_fetch / wiki_search / wiki_answer / MCP，结果只在
工具卡片里一闪而过）。本模块负责第二条管道：producer 在转发 OBSERVING
事件时调用 :func:`extract_sources_from_tool`，把工具结果解析成结构化来源
条目，done 前以 ``sources_used`` 流事件推送并随 assistant 行落盘。

条目形状（``kind`` 是前端分组的依据）::

    {"kind": "web",  "title": str, "url": str, "snippet": str, "query": str}
    {"kind": "wiki", "title": str, "path": str, "snippet": str, "score": float}
    {"kind": "tool", "server": str, "tool": str, "preview": str}

设计约束
--------
- 纯函数 + 防御式解析：``content_json`` 是 run_loop 放进 OBSERVING 事件的
  ``json.dumps(...)`` 字符串（UI 事件保留全文）。畸形 JSON / 形状不符 /
  未知工具一律返回空列表，绝不抛错——引用属增强信息，绝不影响对话主流程
  （对齐 R17-E 降级铁律）。
- 截断防膨胀：snippet/preview 截短、单次工具调用与整轮累计都有条数上限。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

#: 单条来源的摘要/预览截断长度（前端列表里一行的量级）。
MAX_SNIPPET_CHARS = 160
MAX_PREVIEW_CHARS = 120

#: 单次工具调用最多提取的来源条数（web_search limit 理论可传很大）。
MAX_SOURCES_PER_TOOL = 20

#: 整轮 run 累计的来源条数上限（merge 时生效）。
SOURCES_CAP = 50

#: 走来源提取的工具名（MCP 走 ``mcp__<server>__<tool>`` 前缀单独判定）。
_WEB_SEARCH = "web_search"
_WEB_FETCH = "web_fetch"
_WIKI_SEARCH = "wiki_search"
_WIKI_ANSWER = "wiki_answer"


def _shorten(text: Any, limit: int) -> str:
    """截断为单行短摘要；非字符串安全转 str。"""
    if text is None:
        return ""
    collapsed = " ".join(str(text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(0, limit - 1)] + "…"


def _host_of(url: str) -> str:
    try:
        return urlsplit(url).netloc or url
    except Exception:  # noqa: BLE001 — 降级铁律：畸形 url 原样返回
        return url


def _as_score(value: Any) -> Optional[float]:
    """json 数值 → 保留两位小数；非数值（bool 属 int 子类, 一并排除）→ None。

    py3.8 兼容: 不写 ``isinstance(x, (int, float))``（ruff UP038）, 也不写
    ``int | float``（3.10+ 语法, win7 后端仍跑 py3.8）。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return round(value, 2)
    if isinstance(value, float):
        return round(value, 2)
    return None


def _as_dict(payload: Any) -> Dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _extract_web_search(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    query = _shorten(payload.get("query"), MAX_SNIPPET_CHARS)
    sources: List[Dict[str, Any]] = []
    for item in (payload.get("results") or [])[:MAX_SOURCES_PER_TOOL]:
        row = _as_dict(item)
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        title = _shorten(row.get("title"), MAX_SNIPPET_CHARS) or _host_of(url)
        sources.append(
            {
                "kind": "web",
                "title": title,
                "url": url,
                "snippet": _shorten(row.get("snippet"), MAX_SNIPPET_CHARS),
                "query": query,
            }
        )
    return sources


def _extract_web_fetch(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    url = str(payload.get("url") or "").strip()
    if not url:
        return []
    title = _shorten(payload.get("title"), MAX_SNIPPET_CHARS) or _host_of(url)
    return [
        {
            "kind": "web",
            "title": title,
            "url": url,
            "snippet": _shorten(payload.get("content"), MAX_SNIPPET_CHARS),
        }
    ]


def _extract_wiki_search(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    for item in (payload.get("results") or [])[:MAX_SOURCES_PER_TOOL]:
        row = _as_dict(item)
        path = str(row.get("path") or "").strip()
        if not path:
            continue
        score = row.get("score")
        sources.append(
            {
                "kind": "wiki",
                "title": _shorten(row.get("title"), MAX_SNIPPET_CHARS) or path,
                "path": path,
                "snippet": _shorten(row.get("snippet"), MAX_SNIPPET_CHARS),
                "score": _as_score(score),
            }
        )
    return sources


def _extract_wiki_answer(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    for item in (payload.get("citations") or [])[:MAX_SOURCES_PER_TOOL]:
        row = _as_dict(item)
        path = str(row.get("path") or "").strip()
        if not path:
            continue
        sources.append(
            {
                "kind": "wiki",
                "title": _shorten(row.get("title"), MAX_SNIPPET_CHARS) or path,
                "path": path,
                "snippet": _shorten(row.get("excerpt"), MAX_SNIPPET_CHARS),
                "score": None,
            }
        )
    return sources


def _split_mcp_name(name: str) -> tuple:
    # MCP 工具名为 ``mcp__<server>__<tool>``（前缀 ``mcp__`` 是 LLM 可见的）。
    parts = name.split("__")
    if len(parts) >= 3:
        return parts[1], "__".join(parts[2:])
    return name, name


def _extract_mcp_tool(name: str, payload: Any) -> List[Dict[str, Any]]:
    server, tool = _split_mcp_name(name)
    if isinstance(payload, dict):
        # McpTool 成功时 content 为 str 或 {"text": ..., "metadata": ...}。
        preview_source = payload.get("text") if "text" in payload else payload
    else:
        preview_source = payload
    preview = _shorten(preview_source, MAX_PREVIEW_CHARS)
    if not preview:
        return []
    return [{"kind": "tool", "server": server, "tool": tool, "preview": preview}]


def _dedup_key(source: Dict[str, Any]) -> tuple:
    kind = source.get("kind")
    if kind == "web":
        return ("web", str(source.get("url") or ""))
    if kind == "wiki":
        return ("wiki", str(source.get("path") or ""))
    if kind == "memory":
        # R86: @memory: 实体引用命中（title = @memory:query [类型]）
        return ("memory", str(source.get("title") or ""))
    return ("tool", str(source.get("server") or ""), str(source.get("tool") or ""))


def merge_sources(
    accumulated: List[Dict[str, Any]], incoming: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """把新提取的来源并入累计列表：按 url/path 去重，总量 cap 到
    :data:`SOURCES_CAP`。纯函数，不修改入参。"""
    if not incoming:
        return list(accumulated)
    seen = {_dedup_key(s) for s in accumulated if isinstance(s, dict)}
    merged = list(accumulated)
    for source in incoming:
        if len(merged) >= SOURCES_CAP:
            break
        if not isinstance(source, dict):
            continue
        key = _dedup_key(source)
        if key in seen:
            continue
        seen.add(key)
        merged.append(source)
    return merged


#: dict 形结果 → 提取函数（MCP 工具走前缀判定, 不在此表）。
_DICT_EXTRACTORS = {
    _WEB_SEARCH: lambda payload: _extract_web_search(payload),
    _WEB_FETCH: lambda payload: _extract_web_fetch(payload),
    _WIKI_SEARCH: lambda payload: _extract_wiki_search(payload),
    _WIKI_ANSWER: lambda payload: _extract_wiki_answer(payload),
}


def _parse_payload(content_json: Any) -> Any:
    """把 ``ToolCallResult.content``（json.dumps 过的字符串）解析回对象；
    非 str 原样透传（个别路径直接给 dict）；畸形 JSON 返回 None。"""
    if not isinstance(content_json, str):
        return content_json
    try:
        return json.loads(content_json)
    except (ValueError, TypeError):
        return None


def extract_sources_from_tool(name: str, content_json: Any) -> List[Dict[str, Any]]:
    """从 OBSERVING 事件的工具结果解析结构化来源条目。

    Args:
        name: 工具注册名（``web_search`` / ``web_fetch`` / ``wiki_search`` /
            ``wiki_answer`` / ``mcp__<server>__<tool>`` …）。
        content_json: ``ToolCallResult.content``——run_loop 序列化过的 JSON
            字符串（个别路径也可能是非字符串，同样防御）。

    Returns:
        来源条目列表（可能为空）。任何异常都降级为空列表。
    """
    try:
        if not name:
            return []
        payload = _parse_payload(content_json)
        if name.startswith("mcp__"):
            return _extract_mcp_tool(name, payload)
        extractor = _DICT_EXTRACTORS.get(name)
        if extractor is None or payload is None:
            return []
        return extractor(_as_dict(payload))
    except Exception as exc:  # noqa: BLE001 — 降级铁律
        logger.debug(f"sources extract skipped for {name}: {exc}")
        return []
