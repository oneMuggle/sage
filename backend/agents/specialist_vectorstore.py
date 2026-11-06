"""M2-Task 1 — 专家私有知识向量库。

约定路径::

    <specialists_root>/<agent_id>/vectors.json

复用 wiki 的 JSON ``VectorStore``（余弦相似度、幂等 upsert），不触碰
wiki/attachment/project_material 三层现有存储（参见
``docs/plans/2026-11-03_m2-knowledge-binding.md`` §1 「M2 实施策略」）。

page_path 约定:

- 命名空间前缀 ``specialist-knowledge/`` + 知识库内的相对路径
- 反斜杠自动转 ``/``（跨平台一致）；绝对路径 / 路径穿越 / 空路径
  拒绝（与 ``is_agent_id_safe`` 同源，避免不同专家互相覆盖）

嵌入调用通过注入 ``http_post``（wiki ``attachment_rag`` 同口径），
便于单测 fake 与未来替换嵌入提供商。

Pydantic v1/v2 双兼容:

- 不依赖 pydantic；纯 dataclass + 字面常量 + stdlib。
- 全部类型走 ``typing``，避免 ``list[...]`` 仅在 3.9+ 可用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List

from backend.skills.specialist_skills import is_agent_id_safe, specialists_root
from backend.wiki.embeddings import (
    EmbeddingConfig,
    build_embed_request,
    chunk_markdown,
    parse_embed_response,
)
from backend.wiki.vectorstore import SearchHit, VectorStore, read_stored_dim

logger = logging.getLogger(__name__)

#: 专家私有向量库的 page_path 前缀。
SPECIALIST_KNOWLEDGE_PAGE_PREFIX = "specialist-knowledge/"


class SpecialistVectorStoreError(RuntimeError):
    """非法路径 / 嵌入失败 / 维度不匹配。

    与 ``AttachmentRagError`` 同级：调用方可据此区分业务错误与系统
    故障，决定是否 fail-open（返回空结果）还是 5xx。
    """


@dataclass
class SpecialistIndexResult:
    """索引结果；``chunks == 0`` 表示无可索引文本（空文档），未落盘。"""

    agent_id: str
    page_path: str
    chunks: int
    dim: int


# =====================================================================
# 路径约定
# =====================================================================


def specialist_vectors_path(agent_id: str) -> Path:
    """专家私有向量库存储路径。

    ``agent_id`` 必须通过 ``is_agent_id_safe`` 校验——与专家私有
    技能目录同契约——避免路径穿越或写入隐藏目录。
    """
    if not is_agent_id_safe(agent_id):
        raise SpecialistVectorStoreError(f"非法 agent_id: {agent_id!r}")
    return specialists_root() / agent_id / "vectors.json"


def specialist_page_path(rel_path: str) -> str:
    """将知识库内相对路径归一为 ``specialist-knowledge/<path>``。

    拒绝空串、绝对路径、含 ``..`` / 空片段的路径；反斜杠转 ``/``。
    """
    if not rel_path:
        raise SpecialistVectorStoreError("空知识文件路径")

    normalized = rel_path.replace("\\", "/")
    parsed = PurePosixPath(normalized)
    if parsed.is_absolute():
        raise SpecialistVectorStoreError(f"知识文件路径必须为相对路径: {rel_path!r}")

    if any(part in ("", "..") for part in parsed.parts):
        raise SpecialistVectorStoreError(f"知识文件路径含非法片段: {rel_path!r}")

    return f"{SPECIALIST_KNOWLEDGE_PAGE_PREFIX}{parsed.as_posix()}"


# =====================================================================
# 索引 / 检索 / 删除
# =====================================================================


def _open_or_raise(storage_path: Path, dim: int) -> VectorStore:
    """以指定维度打开存储；维度不一致 → ``SpecialistVectorStoreError``。"""
    try:
        return VectorStore.open_at(storage_path, dim)
    except ValueError as exc:
        raise SpecialistVectorStoreError(f"专家私有向量库维度不一致: {exc}") from exc


async def index_specialist_document(
    *,
    agent_id: str,
    rel_path: str,
    text: str,
    embed_config: EmbeddingConfig,
    http_post: Callable[[str, Dict[str, str], dict], Any],
    target_chunk_size: int = 500,
) -> SpecialistIndexResult:
    """分块 → 嵌入 → 落库（幂等替换该知识文件的全部 chunk）。

    Args:
        agent_id: 专家 id（校验安全）
        rel_path: 知识库内相对路径（校验 + 归一为 page_path）
        text: 已提取的全文；空 / 纯空白 → 不索引、不建存储
        embed_config: 嵌入端点配置（base_url/api_key/model/dim）
        http_post: 注入的 HTTP 客户端（与 wiki ingest 同签名）
        target_chunk_size: chunk_markdown 目标块大小（字符）

    Raises:
        SpecialistVectorStoreError: 路径非法 / 嵌入失败 / 维度不一致。
    """
    page_path = specialist_page_path(rel_path)
    storage_path = specialist_vectors_path(agent_id)

    chunks = chunk_markdown(text, target_chunk_size=target_chunk_size)
    if not chunks:
        return SpecialistIndexResult(agent_id, page_path, 0, embed_config.dim)

    embed_req = build_embed_request(embed_config, chunks)
    try:
        response = await http_post(embed_req.url, embed_req.headers, embed_req.body)
    except Exception as exc:
        raise SpecialistVectorStoreError(f"嵌入请求失败: {exc}") from exc

    try:
        vectors = parse_embed_response(response, embed_config.dim)
    except (ValueError, TypeError) as exc:
        raise SpecialistVectorStoreError(f"嵌入响应不可解析: {exc}") from exc
    if len(vectors) != len(chunks):
        raise SpecialistVectorStoreError(
            f"嵌入数量与分块不符: {len(vectors)} != {len(chunks)}"
        )

    store = _open_or_raise(storage_path, embed_config.dim)
    store.upsert_chunks(
        page_path,
        [
            (idx, chunk, vector)
            for idx, (chunk, vector) in enumerate(zip(chunks, vectors))  # noqa: B905 — strict 仅 3.10+
        ],
    )
    logger.info(
        "专家私有向量索引完成: agent=%s rel=%s chunks=%d dim=%d",
        agent_id, rel_path, len(chunks), embed_config.dim,
    )
    return SpecialistIndexResult(agent_id, page_path, len(chunks), embed_config.dim)


def search_specialist_private(
    *,
    agent_id: str,
    query_vector: List[float],
    limit: int = 5,
) -> List[SearchHit]:
    """向量检索当前专家的私有知识 chunk。

    存储不存在或维度不可读 → 空列表（未索引不是错误，与
    ``search_attachments`` 同契约）。
    """
    storage_path = specialist_vectors_path(agent_id)
    if not storage_path.exists():
        return []
    stored_dim = read_stored_dim(storage_path)
    if stored_dim is None or stored_dim != len(query_vector):
        return []
    store = VectorStore.open_at(storage_path, stored_dim)
    return store.search(list(query_vector), limit)


def remove_specialist_document(
    *, agent_id: str, rel_path: str,
) -> int:
    """删除某知识文件的全部 chunk；返回移除记录数（未索引 → 0）。"""
    storage_path = specialist_vectors_path(agent_id)
    if not storage_path.exists():
        return 0
    stored_dim = read_stored_dim(storage_path)
    if stored_dim is None:
        return 0
    store = VectorStore.open_at(storage_path, stored_dim)
    return store.delete_by_page(specialist_page_path(rel_path))
