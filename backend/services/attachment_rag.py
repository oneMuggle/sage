"""聊天附件向量索引库层（聊天文件 RAG 第一切片，r57）。

复用 wiki 的三块地基——分块（chunk_markdown）、嵌入请求构建
（build_embed_request / parse_embed_response）、向量存储（VectorStore）——
为聊天附件（DOCUMENT 类媒体：txt/md/pdf/docx 提取文本）提供
索引 / 检索 / 删除的纯库函数。

依赖全部显式注入（嵌入配置 + http_post + 存储路径），与 wiki ingest
的可测性设计同口径；路由接线、嵌入配置来源（provider 设置 or 请求级）
是产品决策，由后续切片决定——本层不猜。

page_path 约定：``chat-attachment/<media_id>``，重复索引幂等替换
（VectorStore.upsert_chunks 的 delete-then-insert 语义）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.wiki.embeddings import (
    EmbeddingConfig,
    build_embed_request,
    chunk_markdown,
    parse_embed_response,
)
from backend.wiki.vectorstore import SearchHit, VectorStore

logger = logging.getLogger(__name__)

ATTACHMENT_PAGE_PREFIX = "chat-attachment/"


def attachment_vector_store_path(data_root: Path) -> Path:
    """附件向量库统一路径约定：<data_root>/rag/attachments.json（r58）。"""
    return data_root / "rag" / "attachments.json"


def _stored_dim(storage_path: Path) -> Optional[int]:
    """从存储文件读记录时的向量维度；不可读 → None。"""
    try:
        data = json.loads(storage_path.read_text(encoding="utf-8"))
        dim = data.get("dim") if isinstance(data, dict) else None
        return int(dim) if dim is not None else None
    except (OSError, ValueError, TypeError):
        return None


class AttachmentRagError(RuntimeError):
    """嵌入调用失败或响应与分块不匹配（调用方决定 fail-open 或报错）。"""


@dataclass
class AttachmentIndexResult:
    """索引结果；chunks=0 表示无可索引文本（空文档），未落盘。"""

    media_id: str
    page_path: str
    chunks: int
    dim: int


def attachment_page_path(media_id: str) -> str:
    """附件在向量库中的 page_path 键。"""
    return f"{ATTACHMENT_PAGE_PREFIX}{media_id}"


async def index_attachment(
    *,
    media_id: str,
    text: str,
    storage_path: Path,
    embed_config: EmbeddingConfig,
    http_post: Callable[[str, Dict[str, str], dict], Any],
    target_chunk_size: int = 500,
) -> AttachmentIndexResult:
    """分块 → 嵌入 → 落库（幂等替换该附件的全部 chunk）。

    Args:
        media_id: 附件媒体 id（MediaStore 命名空间）
        text: 已提取的附件全文（空/纯空白 → 不索引）
        storage_path: 向量库 JSON 路径（独立于 wiki 的 .llm-wiki/vectors.json）
        embed_config: 嵌入端点配置（base_url/api_key/model/dim）
        http_post: 注入的 HTTP 客户端（wiki ingest 同签名，测试可换 fake）
        target_chunk_size: chunk_markdown 目标块大小（字符）

    Raises:
        AttachmentRagError: 嵌入请求失败、响应不可解析、向量数与分块数不符。
    """
    page_path = attachment_page_path(media_id)
    chunks = chunk_markdown(text, target_chunk_size=target_chunk_size)
    if not chunks:
        return AttachmentIndexResult(media_id, page_path, 0, embed_config.dim)

    embed_req = build_embed_request(embed_config, chunks)
    try:
        response = await http_post(embed_req.url, embed_req.headers, embed_req.body)
    except Exception as exc:
        raise AttachmentRagError(f"嵌入请求失败: {exc}") from exc

    try:
        vectors = parse_embed_response(response, embed_config.dim)
    except (ValueError, TypeError) as exc:
        raise AttachmentRagError(f"嵌入响应不可解析: {exc}") from exc
    if len(vectors) != len(chunks):
        raise AttachmentRagError(
            f"嵌入数量与分块不符: {len(vectors)} != {len(chunks)}"
        )

    store = VectorStore.open_at(storage_path, embed_config.dim)
    store.upsert_chunks(
        page_path,
        [
            (idx, chunk, vector)
            for idx, (chunk, vector) in enumerate(zip(chunks, vectors))  # noqa: B905 — strict keyword is unavailable on Python 3.8
        ],
    )
    logger.info("附件向量索引完成: %s chunks=%d dim=%d", media_id, len(chunks), embed_config.dim)
    return AttachmentIndexResult(media_id, page_path, len(chunks), embed_config.dim)


def search_attachments(
    *,
    query_vector: List[float],
    storage_path: Path,
    dim: Optional[int] = None,
    limit: int = 5,
    media_ids: Optional[List[str]] = None,
) -> List[SearchHit]:
    """向量检索附件 chunk。

    存储不存在 → 空列表（未索引不是错误）。dim 缺省时从存储文件读取
    （r58：删除/检索路由不要求调用方知道维度）。media_ids 给定时只在
    这些附件的 page_path 范围内取命中（跨附件全局排序后过滤）。
    """
    if not storage_path.exists():
        return []
    resolved_dim = dim if dim is not None else _stored_dim(storage_path)
    if resolved_dim is None:
        return []
    store = VectorStore.open_at(storage_path, resolved_dim)
    hits = store.search(list(query_vector), limit)
    if media_ids is None:
        return hits
    wanted = {attachment_page_path(m) for m in media_ids}
    return [hit for hit in hits if hit.page_path in wanted]


def remove_attachment(*, media_id: str, storage_path: Path, dim: Optional[int] = None) -> int:
    """删除附件的全部向量；返回移除的记录数（未索引 → 0）。"""
    if not storage_path.exists():
        return 0
    resolved_dim = dim if dim is not None else _stored_dim(storage_path)
    if resolved_dim is None:
        return 0
    store = VectorStore.open_at(storage_path, resolved_dim)
    return store.delete_by_page(attachment_page_path(media_id))
