"""聊天附件注入上下文构建（RAG 切片 4a，r66）。

单一决策编排：给定附件全文与用户 query，决定注入什么——
- 全文不超过注入上限 → 截断全文（现状口径）；
- 超限且聊天请求携带 attachment_rag 配置 → 嵌入 query + 附件 chunk
  检索（r58 库层）→ 「首段 + top_k 命中块」注入；
- 超限未配置 → 注入前 N 字符（不回归）。

任何异常返回 None（fail-safe：附件注入绝不阻断聊天，R37 口径）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from backend.services.attachment_rag import search_attachments

logger = logging.getLogger(__name__)

MAX_TEXT_INJECT_CHARS = 100_000
#: 检索注入时保留的文档开头字符数（保证基本上下文）
_HEAD_CHARS = 2_000
_DEFAULT_TOP_K = 6
#: 查询文本嵌入时的截断（嵌入端点上下文有限）
_QUERY_EMBED_CHARS = 2_000

_PAGE_MARKER_RE = re.compile(r"^--- page (\d+) ---$", re.MULTILINE)


def locate_chunk_pages(
    full_text: str, chunk_text: str
) -> Tuple[Optional[int], Optional[int]]:
    """反查 chunk 在带页标记全文中的页码范围（2026-11-15）。

    检索层只存 chunk 文本，不存页码；注入时用 chunk 文本在全文中的偏移
    数页标记。定位失败（chunk 被归一化/重复文本）返回 (None, None)，
    调用方不展示页码即可。
    """
    if not full_text or not chunk_text:
        return None, None
    offset = full_text.find(chunk_text)
    if offset < 0:
        snippet = chunk_text[:120]
        offset = full_text.find(snippet) if snippet else -1
    if offset < 0:
        return None, None

    prefix_pages = list(_PAGE_MARKER_RE.finditer(full_text, 0, offset))
    chunk_pages = list(
        _PAGE_MARKER_RE.finditer(full_text, offset, min(len(full_text), offset + len(chunk_text)))
    )
    start = int(prefix_pages[-1].group(1)) if prefix_pages else None
    if chunk_pages:
        first = int(chunk_pages[0].group(1))
        last = int(chunk_pages[-1].group(1))
        start = first if start is None else start
        return start, max(last, start)
    if start is None:
        return None, None
    return start, start


@dataclass
class ChunkCitation:
    """检索命中片段的溯源信息（r73 引用明细；2026-11-15 增页码）。"""

    index: int  # chunk_index + 1（1 起始，与注入块内标注一致）
    score: float  # 余弦相似度
    page_start: Optional[int] = None
    page_end: Optional[int] = None


@dataclass
class AttachmentContextResult:
    """注入决策结果：text 为注入块；mode = full | truncated | rag。"""

    text: str
    mode: str
    #: mode=rag 时命中的片段明细（引用溯源事件用）
    chunks: List[ChunkCitation] = None  # type: ignore[assignment] — 空列表由 __post_init__ 归一

    def __post_init__(self) -> None:
        if self.chunks is None:
            self.chunks = []


@dataclass
class AttachmentRagOptions:
    """聊天请求携带的附件检索配置（opt-in；请求级嵌入配置与 wiki 同口径）。"""

    embed: Dict[str, str]
    top_k: int = _DEFAULT_TOP_K


async def build_attachment_context(
    media_id: str,
    *,
    full_text: str,
    query: str,
    rag: Optional[AttachmentRagOptions],
    store_path: Any,
    query_embedder: Optional[Callable[[str, Dict[str, str]], Awaitable[List[List[float]]]]] = None,
) -> AttachmentContextResult:
    """返回该附件应注入的文本块；fail-safe 异常返回 None（调用方跳过）。

    Args:
        media_id: 附件媒体 id（注入块标注用）
        full_text: 已提取的附件全文（未截断）
        query: 用户消息（作为检索 query；嵌入前截断）
        rag: 请求级检索配置；None = 不做检索
        store_path: 附件向量库路径（无索引文件时检索返回空 → 回退截断）
        query_embedder: 异步 (query_text, embed_cfg) -> [[float]]；
            生产实现走 embed 端点，测试注入 fake。rag 配置了但未提供 →
            按未配置处理（截断注入）。
    """
    try:
        if len(full_text) <= MAX_TEXT_INJECT_CHARS:
            return AttachmentContextResult(
                full_text[:MAX_TEXT_INJECT_CHARS], "full"
            )
        if rag is None or query_embedder is None:
            return AttachmentContextResult(
                full_text[:MAX_TEXT_INJECT_CHARS], "truncated"
            )

        rag_text = await _rag_injection(
            media_id,
            full_text=full_text,
            query=query,
            rag=rag,
            store_path=store_path,
            query_embedder=query_embedder,
        )
        if rag_text is not None:
            return rag_text
        # 检索不可用（无命中/嵌入失败/无索引）→ 回退现状截断注入
        return AttachmentContextResult(
            full_text[:MAX_TEXT_INJECT_CHARS], "truncated"
        )
    except Exception as exc:  # noqa: BLE001 — fail-safe（R37 口径）
        logger.debug("附件上下文构建失败（跳过注入）: %s: %s", media_id, exc)
        return None


async def _rag_injection(
    media_id: str,
    *,
    full_text: str,
    query: str,
    rag: AttachmentRagOptions,
    store_path: Any,
    query_embedder: Callable[[str, Dict[str, str]], Awaitable[List[List[float]]]],
) -> Optional[str]:
    """超长文档的检索注入块；不可用（失败/无命中）返回 None。"""
    try:
        vectors = await query_embedder(query[:_QUERY_EMBED_CHARS], dict(rag.embed))
        if not vectors:
            return None
        hits = search_attachments(
            query_vector=vectors[0],
            storage_path=store_path,
            media_ids=[media_id],
            limit=rag.top_k,
        )
        if not hits:
            return None
        parts: List[str] = [
            "[文档超长，已按相关度检索；开头 "
            f"{_HEAD_CHARS} 字符 + top {len(hits)} 片段]",
            full_text[:_HEAD_CHARS],
        ]
        for hit in hits:
            parts.append(
                f"[chunk {hit.chunk_index + 1} 相关度 {hit.score:.2f}]\n{hit.content}"
            )
        logger.info(
            "附件检索注入: %s 超限全文 %d 字符 → top %d chunk",
            media_id,
            len(full_text),
            len(hits),
        )
        citations: List[ChunkCitation] = []
        for hit in hits:
            page_start, page_end = locate_chunk_pages(full_text, hit.content)
            citations.append(
                ChunkCitation(
                    index=hit.chunk_index + 1,
                    score=hit.score,
                    page_start=page_start,
                    page_end=page_end,
                )
            )
        return AttachmentContextResult(
            f"<attached_document id={media_id!r} mode=rag>\n"
            + "\n\n".join(parts)
            + "\n</attached_document>",
            "rag",
            citations,
        )
    except Exception as rag_exc:  # noqa: BLE001 — 检索失败回退截断注入
        logger.debug("附件检索失败，回退截断注入 %s: %s", media_id, rag_exc)
        return None


async def embed_query_via_http(
    query: str, embed_cfg: Dict[str, str]
) -> List[List[float]]:
    """生产实现的 query 嵌入（embed 端点直连；测试用 fake 替代）。"""
    import httpx

    from backend.wiki.embeddings import build_embed_request, parse_embed_response

    request = build_embed_request(embed_cfg, [query])  # type: ignore[arg-type]
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(request.url, headers=request.headers, json=request.body)
        resp.raise_for_status()
        return parse_embed_response(resp.text)
