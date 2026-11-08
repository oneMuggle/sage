"""M2-Task 3 — 专家知识检索路由层。

按 ``KnowledgeBinding.source_type`` 把查询扇出到对应存储，每路返回
一份排序结果，最后用 :func:`backend.agents.rrf.reciprocal_rank_fusion`
融合为统一的 ``RetrievedChunk`` 列表。

设计要点：

- **可注入检索器**：``searchers`` 为 ``{source_type: searcher}`` 映射，
  签名 ``(binding, query, query_vector, limit) -> List[SourceHit]``（同步）。
  单元测试全部注入 fake；生产默认见 ``_DEFAULT_SEARCHERS``。
- **查询嵌入懒加载**：仅当实际派发到向量源（wiki_project /
  specialist_private）时才调用 ``embed_query``；project_material 内部
  自带嵌入器，接收文本查询。嵌入失败只跳过向量源，不拖垮整体。
- **失败隔离**：每个源独立线程 + ``asyncio.wait_for`` 超时；任一源
  异常/超时 → 记 warning 并跳过（fail-open）。
- **只读安全**：打开 wiki ``VectorStore`` 前先检查存储文件存在且维度
  匹配——``VectorStore.open()`` 在文件缺失时会创建空库并落盘。
- **绑定去重**：同一 ``(source_type, source_id)``（specialist_private
  再加 ``agent_id``）只检索一次。

当前实现覆盖四路源（wiki_project / project_material /
specialist_private / sage_docs）；``zotero_collection`` / ``workspace_fts``
暂未接入（zotero 的 ``semantic_search`` 结果不带 collection 键，无法按绑定
集合过滤），未知源类型静默跳过，见 M2 计划文档的跟进项。

Python 3.8 兼容：``typing`` 泛型 + ``loop.run_in_executor``。
"""

from __future__ import annotations

import asyncio
import functools
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.agents.knowledge_binding import KnowledgeBinding
from backend.agents.rrf import reciprocal_rank_fusion
from backend.agents.specialist_vectorstore import search_specialist_private
from backend.wiki.vectorstore import read_stored_dim
from backend.wiki.vectorstore_factory import backend_name as wiki_backend_name, open_vector_store

logger = logging.getLogger(__name__)

#: 最终返回的融合结果条数（默认）。
DEFAULT_RETRIEVE_LIMIT = 5

#: 单路内部召回深度；比最终 limit 更深，给 RRF 留出融合空间。
DEFAULT_SOURCE_LIMIT = 5

#: 单路检索超时（秒）。超时即跳过该源，不阻塞整体。
DEFAULT_SOURCE_TIMEOUT_S = 5.0

#: 需要查询向量的源类型。
VECTOR_SOURCE_TYPES: Tuple[str, ...] = ("wiki_project", "specialist_private")

#: wiki 向量库 HNSW 后端索引文件名（与 HNSWVectorStore 约定一致）。
_WIKI_HNSW_FILENAME = "vectors.hnsw"

#: wiki 向量库 JSON 后端索引目录与文件名（与 VectorStore.open 约定一致）。
_WIKI_JSON_DIRNAME = ".llm-wiki"
_WIKI_JSON_FILENAME = "vectors.json"


@dataclass(frozen=True)
class SourceHit:
    """单个检索源的原始命中（尚未融合）。"""

    doc_id: str
    content: str
    loc: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievedChunk:
    """融合后的检索结果，携带绑定元数据与引用定位字段。"""

    doc_id: str
    content: str
    score: float
    source_type: str
    source_id: str
    binding_id: str
    binding_name: str
    agent_id: str
    loc: Dict[str, Any] = field(default_factory=dict)


# searcher 签名：(binding, query, query_vector_or_None, limit) -> List[SourceHit]
Searcher = Any
EmbedQuery = Any

# =====================================================================
# 默认检索器（生产路径；单元测试注入 fake 覆盖）
# =====================================================================

_material_indexer_holder: List[Any] = []
_embedder_holder: List[Any] = []


def _get_project_material_indexer() -> Any:
    """惰性构造并复用 ProjectMaterialIndexer（自带嵌入器与 sqlite-vec）。"""
    if not _material_indexer_holder:
        from backend.services.project_material_indexer import ProjectMaterialIndexer

        _material_indexer_holder.append(ProjectMaterialIndexer())
    return _material_indexer_holder[0]


def _get_embedder() -> Any:
    """惰性构造并复用嵌入器（Hash/ONNX/HTTP 由工厂按配置选择）。"""
    if not _embedder_holder:
        from backend.memory.embedder_factory import create_embedder

        _embedder_holder.append(create_embedder())
    return _embedder_holder[0]


async def _default_embed_query(query: str) -> List[float]:
    """默认查询嵌入：CPU 密集部分放线程池，避免阻塞事件循环。"""
    embedder = _get_embedder()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, embedder.encode, query)


def _wiki_path_prefix(binding: KnowledgeBinding) -> Optional[str]:
    prefix = binding.filters.get("path_prefix")
    return prefix.strip() if isinstance(prefix, str) and prefix.strip() else None


def _search_wiki_project(
    binding: KnowledgeBinding,
    query: str,
    query_vector: Optional[List[float]],
    limit: int,
) -> List[SourceHit]:
    """wiki_project → 项目 ``.llm-wiki`` 向量库（只读打开）。"""
    if not query_vector:
        return []

    from backend.data.project_repo import ProjectRepository

    project = ProjectRepository().get(binding.source_id)
    if project is None or not project.path:
        logger.warning("wiki_project 绑定目标项目不存在: %s", binding.source_id)
        return []

    root = Path(project.path)
    json_store = root / _WIKI_JSON_DIRNAME / _WIKI_JSON_FILENAME

    if wiki_backend_name() == "hnsw":
        if not (root / _WIKI_JSON_DIRNAME / _WIKI_HNSW_FILENAME).exists():
            return []
        store = open_vector_store(root, len(query_vector))
    else:
        if not json_store.exists():
            return []
        stored_dim = read_stored_dim(json_store)
        if stored_dim is None or stored_dim != len(query_vector):
            logger.warning(
                "wiki 向量维度不匹配（存储 %s / 查询 %d），跳过: %s",
                stored_dim,
                len(query_vector),
                binding.source_id,
            )
            return []
        store = open_vector_store(root, stored_dim)

    prefix = _wiki_path_prefix(binding)
    # 前缀过滤在命中级应用：多取一些候选再做过滤。
    fetch_limit = limit * 4 if prefix else limit
    hits = store.search(list(query_vector), fetch_limit)

    results: List[SourceHit] = []
    for hit in hits:
        if prefix is not None and not hit.page_path.startswith(prefix):
            continue
        results.append(
            SourceHit(
                doc_id=f"{hit.page_path}::{hit.chunk_index}",
                content=hit.content,
                loc={"page_path": hit.page_path, "chunk_index": hit.chunk_index},
            )
        )
        if len(results) >= limit:
            break
    return results


def _search_project_material(
    binding: KnowledgeBinding,
    query: str,
    query_vector: Optional[List[float]],
    limit: int,
) -> List[SourceHit]:
    """project_material → sqlite-vec 语义检索（自带嵌入，按 project_id 过滤）。"""
    indexer = _get_project_material_indexer()
    hits = indexer.search(binding.source_id, query, top_k=limit)
    return [
        SourceHit(
            doc_id=f"{hit.material_id}::{hit.chunk_index}",
            content=hit.content,
            loc={
                "material_id": hit.material_id,
                "chunk_index": hit.chunk_index,
                "project_id": hit.project_id,
            },
        )
        for hit in hits
    ]


def _search_specialist_private(
    binding: KnowledgeBinding,
    query: str,
    query_vector: Optional[List[float]],
    limit: int,
) -> List[SourceHit]:
    """specialist_private → 专家私有向量库（存储缺失/维度不符 → 空）。"""
    if not query_vector:
        return []
    hits = search_specialist_private(
        agent_id=binding.agent_id,
        query_vector=list(query_vector),
        limit=limit,
    )
    return [
        SourceHit(
            doc_id=f"{hit.page_path}::{hit.chunk_index}",
            content=hit.content,
            loc={"page_path": hit.page_path, "chunk_index": hit.chunk_index},
        )
        for hit in hits
    ]


def _search_sage_docs(
    binding: KnowledgeBinding,
    query: str,
    query_vector: Optional[List[float]],
    limit: int,
) -> List[SourceHit]:
    """sage_docs → Sage 内置文档 FTS5 检索（忽略 query_vector）。"""
    from backend.services.sage_docs.search import search_sage_docs

    hits = search_sage_docs(query, limit=limit)
    return [
        SourceHit(
            doc_id=f"{hit.rel_path}::{hit.chunk_index}",
            content=hit.content,
            loc={
                "page_path": hit.rel_path,
                "heading": hit.heading,
                "start_line": hit.start_line,
                "chunk_index": hit.chunk_index,
            },
        )
        for hit in hits
    ]


_DEFAULT_SEARCHERS: Dict[str, Searcher] = {
    "wiki_project": _search_wiki_project,
    "project_material": _search_project_material,
    "specialist_private": _search_specialist_private,
    "sage_docs": _search_sage_docs,
}

# =====================================================================
# 路由层
# =====================================================================


def _binding_key(binding: KnowledgeBinding) -> Tuple[str, str, str]:
    """去重键；specialist_private 归属专家，需带 agent_id 区分。"""
    agent_part = binding.agent_id if binding.source_type == "specialist_private" else ""
    return (binding.source_type, binding.source_id, agent_part)


def _coerce_binding(raw: Any) -> Optional[KnowledgeBinding]:
    if isinstance(raw, KnowledgeBinding):
        return raw
    try:
        return KnowledgeBinding(**dict(raw))
    except (TypeError, ValueError):
        logger.warning("忽略非法知识绑定: %r", raw)
        return None


class KnowledgeRetriever:
    """专家知识检索编排器。

    Args:
        embed_query: 异步查询嵌入函数；默认走 ``create_embedder()``。
        searchers: ``{source_type: searcher}`` 映射；``None`` 使用默认三路。
        source_timeout_s: 单路超时秒数。
    """

    def __init__(
        self,
        *,
        embed_query: Optional[EmbedQuery] = None,
        searchers: Optional[Dict[str, Searcher]] = None,
        source_timeout_s: float = DEFAULT_SOURCE_TIMEOUT_S,
    ) -> None:
        self._embed_query = embed_query or _default_embed_query
        self._searchers = dict(searchers) if searchers is not None else dict(_DEFAULT_SEARCHERS)
        self._timeout_s = source_timeout_s

    async def retrieve(
        self,
        bindings: Any,
        query: str,
        *,
        limit: int = DEFAULT_RETRIEVE_LIMIT,
    ) -> List[RetrievedChunk]:
        """检索并融合。

        Args:
            bindings: ``KnowledgeBinding`` 序列（也接受原始 dict，逐条校验）。
            query: 用户查询；空白 → 直接返回空列表。
            limit: 最终返回条数。

        Returns:
            List[RetrievedChunk]: RRF 分数降序，带绑定元数据与 ``loc``。
        """
        if not query or not query.strip() or limit <= 0:
            return []

        unique: List[KnowledgeBinding] = []
        seen_keys = set()
        for raw in bindings or []:
            binding = _coerce_binding(raw)
            if binding is None:
                continue
            key = _binding_key(binding)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            if binding.source_type not in self._searchers:
                logger.debug(
                    "知识源类型暂未接入检索，跳过: %s (binding=%s)",
                    binding.source_type,
                    binding.id,
                )
                continue
            unique.append(binding)

        if not unique:
            return []

        query_vector = await self._resolve_query_vector(unique, query)

        source_limit = max(DEFAULT_SOURCE_LIMIT, limit)
        dispatched: List[Tuple[KnowledgeBinding, List[SourceHit]]] = []
        for binding in unique:
            needs_vector = binding.source_type in VECTOR_SOURCE_TYPES
            vector = query_vector if needs_vector else None
            if needs_vector and vector is None:
                continue  # 嵌入失败：仅跳过向量源
            hits = await self._run_searcher(binding, query, vector, source_limit)
            if hits:
                dispatched.append((binding, hits))

        if not dispatched:
            return []

        rankings = [[hit.doc_id for hit in hits] for _, hits in dispatched]
        fused = reciprocal_rank_fusion(rankings, top_k=limit)

        # doc_id → (首次出现的绑定与命中)，用于还原内容与元数据。
        origin: Dict[str, Tuple[KnowledgeBinding, SourceHit]] = {}
        for binding, hits in dispatched:
            for hit in hits:
                origin.setdefault(hit.doc_id, (binding, hit))

        chunks: List[RetrievedChunk] = []
        for entry in fused:
            binding, hit = origin[entry.item_id]
            chunks.append(
                RetrievedChunk(
                    doc_id=entry.item_id,
                    content=hit.content,
                    score=entry.score,
                    source_type=binding.source_type,
                    source_id=binding.source_id,
                    binding_id=binding.id,
                    binding_name=binding.name,
                    agent_id=binding.agent_id,
                    loc=dict(hit.loc),
                )
            )
        return chunks

    async def _resolve_query_vector(
        self,
        bindings: List[KnowledgeBinding],
        query: str,
    ) -> Optional[List[float]]:
        """仅当有向量源参与时嵌入查询；失败 → None（跳过向量源）。"""
        needs_vector = any(binding.source_type in VECTOR_SOURCE_TYPES for binding in bindings)
        if not needs_vector:
            return None
        try:
            vector = await asyncio.wait_for(self._embed_query(query), timeout=self._timeout_s)
        except Exception as exc:  # noqa: BLE001 — 嵌入失败必须 fail-open
            logger.warning("查询嵌入失败，跳过向量源: %s", exc)
            return None
        if not vector:
            logger.warning("查询嵌入返回空向量，跳过向量源")
            return None
        return list(vector)

    async def _run_searcher(
        self,
        binding: KnowledgeBinding,
        query: str,
        query_vector: Optional[List[float]],
        limit: int,
    ) -> List[SourceHit]:
        """单路检索：线程池执行 + 超时 + fail-open。"""
        searcher = self._searchers[binding.source_type]
        loop = asyncio.get_running_loop()
        call = functools.partial(searcher, binding, query, query_vector, limit)
        try:
            hits = await asyncio.wait_for(loop.run_in_executor(None, call), timeout=self._timeout_s)
        except asyncio.TimeoutError:  # noqa: UP041 — py38 下与内建 TimeoutError 不互认
            logger.warning(
                "知识源检索超时（%.1fs），跳过: %s/%s",
                self._timeout_s,
                binding.source_type,
                binding.source_id,
            )
            return []
        except Exception as exc:  # noqa: BLE001 — 单源失败不拖垮整体
            logger.warning(
                "知识源检索失败，跳过: %s/%s: %s",
                binding.source_type,
                binding.source_id,
                exc,
            )
            return []
        return list(hits or [])
