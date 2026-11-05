"""M2-Task 4/5 — 专家知识检索注入、引用输出与无命中拒答。

把 :class:`backend.agents.knowledge_retriever.KnowledgeRetriever` 的融合结果
桥接进聊天主流程的三条管道：

1. **动态上下文**：:func:`build_knowledge_context` 生成 ``<knowledge_context>``
   块，由 producer 追加进 ``dynamic_context_parts``（受统一预算裁剪）；
2. **引用来源**：:func:`knowledge_sources_from_chunks` 生成
   ``kind="knowledge"`` 的来源条目，随 ``sources_used`` 流事件推送并落盘，
   前端据此渲染可点击定位的引用 chip；
3. **无命中拒答提示**：当存在绑定但检索返回 0 命中时，返回结构化
   ``no_hit_hint``，引导 LLM 告知用户「知识库无相关内容」。

设计约束：

- **fail-open**：无绑定 / 空查询直接短路；检索异常记 warning 返回空，
  绝不阻断对话主流程（对齐 R17-E 降级铁律）。检索异常**不触发拒答提示**
  （避免误拦——检索挂了不等于知识库里真的没有）。
- **两级截断**：单块正文 ``KNOWLEDGE_CHUNK_MAX_CHARS``，整块
  ``KNOWLEDGE_CONTEXT_MAX_CHARS``，防上下文膨胀。
- **定位字段**：``loc`` 原样透传（page_path / material_id / chunk_index /
  project_id），来源条目同时拍平常用字段供前端直接读取。
- **可观测**：检索耗时通过 ``time.monotonic()`` 计算，以 ``logger.info``
  输出 ``[SPECIALIST_KNOWLEDGE]`` 前缀 span，便于生产排查。

Python 3.8 兼容：``typing`` 泛型，无 PEP 604。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: 整块 ``<knowledge_context>`` 的字符上限（约 1.5k tokens，中英混排）。
KNOWLEDGE_CONTEXT_MAX_CHARS = 6000

#: 单个命中块注入正文的字符上限。
KNOWLEDGE_CHUNK_MAX_CHARS = 1200

#: 来源条目 snippet 的字符上限（与 sources_extractor 同量级）。
KNOWLEDGE_SOURCE_SNIPPET_CHARS = 160

#: 每轮注入/引用的命中条数上限。
DEFAULT_KNOWLEDGE_LIMIT = 5

#: 无命中时注入的拒答提示模板（``{bindings}`` 为逗号分隔的绑定名）。
NO_HIT_HINT_TEMPLATE = (
    "知识库无相关内容：专家绑定的知识源（{bindings}）中未检索到与当前问题相关的资料。"
    "请在回答中明确告知用户知识库暂无相关内容，建议其补充参考资料或调整问题；"
    "不要编造知识库内容。"
)


def knowledge_bindings_from_profile(profile: Any) -> List[Dict[str, Any]]:
    """从 ``agent.profile`` 提取合法绑定 dict 列表（非法项静默丢弃）。"""
    if not isinstance(profile, dict):
        return []
    raw = profile.get("knowledge_bindings")
    if not isinstance(raw, list):
        return []
    return [binding for binding in raw if isinstance(binding, dict)]


def _truncate(text: Any, limit: int) -> str:
    """折叠空白并截断；超限时以省略号结尾。"""
    collapsed = " ".join(str(text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(0, limit - 1)] + "…"


def _loc_hint(chunk: Any) -> str:
    """生成人读的定位提示行（文件 / 资料 / 片段序号）。"""
    loc = chunk.loc if isinstance(chunk.loc, dict) else {}
    parts: List[str] = []
    page_path = loc.get("page_path")
    if page_path:
        parts.append(f"文件：{page_path}")
    material_id = loc.get("material_id")
    if material_id:
        parts.append(f"资料：{material_id}")
    chunk_index = loc.get("chunk_index")
    if isinstance(chunk_index, int):
        parts.append(f"片段：#{chunk_index}")
    return " | ".join(parts)


def build_knowledge_context(chunks: List[Any]) -> str:
    """把检索命中渲染为带编号的 ``<knowledge_context>`` 块。

    Args:
        chunks: :class:`RetrievedChunk` 序列（鸭子类型：需 binding_name /
            source_type / content / loc 字段）。

    Returns:
        注入文本；无命中返回空字符串。总长度不超过
        :data:`KNOWLEDGE_CONTEXT_MAX_CHARS`。
    """
    if not chunks:
        return ""

    header_lines = [
        "<knowledge_context>",
        "以下为专家绑定的知识库检索结果（回答时优先依据这些内容）：",
    ]
    closing = "</knowledge_context>"
    used = sum(len(line) + 1 for line in header_lines)
    body: List[str] = []

    for index, chunk in enumerate(chunks, 1):
        block_lines = [f"[K{index}] {chunk.binding_name}｜{chunk.source_type}"]
        hint = _loc_hint(chunk)
        if hint:
            block_lines.append(hint)
        content = _truncate(chunk.content, KNOWLEDGE_CHUNK_MAX_CHARS)
        if content:
            block_lines.append(content)
        block = "\n".join(block_lines)

        available = KNOWLEDGE_CONTEXT_MAX_CHARS - used - len(closing) - 1
        if available <= 0:
            break
        if len(block) > available:
            block = block[: available - 1] + "…" if available > 1 else ""
        if not block:
            break
        body.append(block)
        used += len(block) + 1

    if not body:
        return ""
    return "\n".join(header_lines + body + [closing])


def knowledge_sources_from_chunks(chunks: List[Any]) -> List[Dict[str, Any]]:
    """把检索命中拍平成 ``sources_used`` 兼容的来源条目。

    条目形状（``kind="knowledge"``）::

        {
          "kind": "knowledge", "title": "wiki/a.md", "path": "wiki/a.md",
          "snippet": "分层架构说明", "score": 0.02,
          "source_type": "wiki_project", "source_id": "proj_1",
          "binding_id": "kb_1", "binding_name": "项目 Wiki",
          "agent_id": "specialist-x", "chunk_index": 0,
          "material_id": None, "project_id": None,
          "loc": {"page_path": "wiki/a.md", "chunk_index": 0},
        }

    ``title`` 优先取定位标识（page_path / material_id），缺失时回落绑定名，
    保证前端 chip 始终有可读文本。
    """
    sources: List[Dict[str, Any]] = []
    for chunk in chunks:
        loc = dict(chunk.loc) if isinstance(chunk.loc, dict) else {}
        page_path = loc.get("page_path")
        material_id = loc.get("material_id")
        project_id = loc.get("project_id")
        if project_id is None and chunk.source_type == "project_material":
            # project_material 的 source_id 即项目 ID（绑定口径）。
            project_id = chunk.source_id
        sources.append(
            {
                "kind": "knowledge",
                "title": page_path or material_id or chunk.binding_name,
                "path": page_path,
                "snippet": _truncate(chunk.content, KNOWLEDGE_SOURCE_SNIPPET_CHARS),
                "score": round(float(chunk.score), 2),
                "source_type": chunk.source_type,
                "source_id": chunk.source_id,
                "binding_id": chunk.binding_id,
                "binding_name": chunk.binding_name,
                "agent_id": chunk.agent_id,
                "chunk_index": loc.get("chunk_index"),
                "material_id": material_id,
                "project_id": project_id,
                "loc": loc,
            }
        )
    return sources


def _binding_display_names(bindings: List[Dict[str, Any]]) -> str:
    """绑定名列表 → 人读字符串（去重、保序、缺名回落 source_type）。"""
    seen: List[str] = []
    for binding in bindings:
        name = str(binding.get("name") or binding.get("source_type") or "").strip()
        if name and name not in seen:
            seen.append(name)
    return "、".join(seen)


async def retrieve_knowledge_context(
    profile: Any,
    query: str,
    *,
    retriever: Optional[Any] = None,
    limit: int = DEFAULT_KNOWLEDGE_LIMIT,
) -> Tuple[str, List[Dict[str, Any]], str]:
    """检索专家绑定知识并产出（上下文块, 来源条目, 无命中拒答提示）。

    Args:
        profile: ``agent.profile``（dict；无绑定视为普通助手）。
        query: 本轮用户消息。
        retriever: 可注入的检索器（默认新建 ``KnowledgeRetriever``）；
            单元测试注入 fake。
        limit: 最终命中条数。

    Returns:
        ``(block, sources, no_hit_hint)``：

        - 正常命中：``(上下文块, 来源条目, "")``；
        - **有绑定但 0 命中**（M2-Task 5 拒答）：``("", [], 拒答提示)``，
          提示包含绑定名，引导 LLM 明确告知「知识库无相关内容」；
        - 无绑定 / 空查询 / 检索异常（fail-open）：``("", [], "")``，
          不触发拒答，调用方无需额外判空。
    """
    bindings = knowledge_bindings_from_profile(profile)
    if not bindings:
        return "", [], ""
    if not query or not str(query).strip():
        return "", [], ""

    if retriever is None:
        from backend.agents.knowledge_retriever import KnowledgeRetriever

        retriever = KnowledgeRetriever()

    started = time.monotonic()
    try:
        chunks = await retriever.retrieve(bindings, query, limit=limit)
    except Exception as exc:  # noqa: BLE001 — 检索属增强，失败必须 fail-open
        elapsed_ms = (time.monotonic() - started) * 1000.0
        logger.warning(
            "[SPECIALIST_KNOWLEDGE] span retrieve status=error elapsed_ms=%.1f "
            "bindings=%d error=%s",
            elapsed_ms,
            len(bindings),
            exc,
        )
        return "", [], ""

    elapsed_ms = (time.monotonic() - started) * 1000.0
    logger.info(
        "[SPECIALIST_KNOWLEDGE] span retrieve status=%s elapsed_ms=%.1f "
        "bindings=%d hits=%d query_chars=%d",
        "hit" if chunks else "no_hit",
        elapsed_ms,
        len(bindings),
        len(chunks),
        len(str(query)),
    )

    if not chunks:
        hint = NO_HIT_HINT_TEMPLATE.format(bindings=_binding_display_names(bindings))
        return "", [], hint

    return build_knowledge_context(chunks), knowledge_sources_from_chunks(chunks), ""
