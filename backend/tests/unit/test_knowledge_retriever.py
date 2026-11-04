"""M2-Task 3 — 专家知识检索路由层测试。

注入 fake 检索器验证：按 binding.source_type 扇出、RRF 融合、去重、
失败隔离、向量源与文本源的查询参数区分、未知源类型跳过。

不触碰真实存储：默认检索器在单元测试中一律被覆盖。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from backend.agents.knowledge_binding import KnowledgeBinding
from backend.agents.knowledge_retriever import (
    KnowledgeRetriever,
    RetrievedChunk,
    SourceHit,
)

pytestmark = pytest.mark.asyncio


def _binding(
    source_type: str,
    source_id: str,
    *,
    agent_id: str = "specialist-x",
    name: str = "知识源",
) -> KnowledgeBinding:
    return KnowledgeBinding(
        agent_id=agent_id,
        source_type=source_type,  # type: ignore[arg-type]
        source_id=source_id,
        name=name,
    )


def _hit(doc_id: str, content: str = "片段", loc: Optional[Dict[str, Any]] = None) -> SourceHit:
    return SourceHit(doc_id=doc_id, content=content, loc=loc or {"chunk_index": 0})


class RecordingSearcher:
    """记录调用参数并返回预设结果的同步检索器。"""

    def __init__(self, results: List[SourceHit], *, error: Optional[Exception] = None):
        self.results = results
        self.error = error
        self.calls: List[Dict[str, Any]] = []

    def __call__(
        self,
        binding: KnowledgeBinding,
        query: str,
        query_vector: Optional[List[float]],
        limit: int,
    ) -> List[SourceHit]:
        self.calls.append(
            {
                "binding": binding,
                "query": query,
                "query_vector": query_vector,
                "limit": limit,
            }
        )
        if self.error is not None:
            raise self.error
        return list(self.results)


async def _fake_embed(query: str) -> List[float]:
    return [0.5, 0.25]


def _retriever(
    *,
    wiki: Optional[RecordingSearcher] = None,
    material: Optional[RecordingSearcher] = None,
    specialist: Optional[RecordingSearcher] = None,
    embed: Any = _fake_embed,
) -> KnowledgeRetriever:
    searchers: Dict[str, Any] = {}
    if wiki is not None:
        searchers["wiki_project"] = wiki
    if material is not None:
        searchers["project_material"] = material
    if specialist is not None:
        searchers["specialist_private"] = specialist
    return KnowledgeRetriever(embed_query=embed, searchers=searchers)


class TestRetrieveFusion:
    async def test_empty_query_returns_empty(self):
        wiki = RecordingSearcher([_hit("w0")])
        retriever = _retriever(wiki=wiki)

        assert await retriever.retrieve([_binding("wiki_project", "proj_1")], "   ") == []
        assert wiki.calls == []

    async def test_no_bindings_returns_empty(self):
        retriever = _retriever()
        assert await retriever.retrieve([], "查询") == []

    async def test_fuses_three_sources_and_ranks_shared_doc_first(self):
        wiki = RecordingSearcher([_hit("w0", "共享"), _hit("w1")])
        material = RecordingSearcher([_hit("m0")])
        specialist = RecordingSearcher([_hit("s0"), _hit("w0", "共享")])
        retriever = _retriever(wiki=wiki, material=material, specialist=specialist)

        chunks = await retriever.retrieve(
            [
                _binding("wiki_project", "proj_1", name="项目 Wiki"),
                _binding("project_material", "proj_1", name="项目资料"),
                _binding("specialist_private", "specialist-x", name="私有目录"),
            ],
            "查询",
        )

        ids = [chunk.doc_id for chunk in chunks]
        assert ids[0] == "w0"
        assert set(ids) == {"w0", "w1", "m0", "s0"}
        # w0 在 wiki 排第 0、specialist 排第 1：1/60 + 1/61
        assert chunks[0].score == pytest.approx(1.0 / 60 + 1.0 / 61)
        assert chunks[0].content == "共享"

    async def test_metadata_from_binding_is_attached(self):
        wiki = RecordingSearcher([_hit("w0", "内容", {"page_path": "wiki/a.md", "chunk_index": 0})])
        retriever = _retriever(wiki=wiki)
        binding = _binding("wiki_project", "proj_1", name="项目 Wiki")

        [chunk] = await retriever.retrieve([binding], "查询")

        assert isinstance(chunk, RetrievedChunk)
        assert chunk.source_type == "wiki_project"
        assert chunk.source_id == "proj_1"
        assert chunk.binding_id == binding.id
        assert chunk.binding_name == "项目 Wiki"
        assert chunk.agent_id == "specialist-x"
        assert chunk.loc == {"page_path": "wiki/a.md", "chunk_index": 0}

    async def test_respects_limit(self):
        wiki = RecordingSearcher([_hit("w0"), _hit("w1"), _hit("w2")])
        retriever = _retriever(wiki=wiki)

        chunks = await retriever.retrieve([_binding("wiki_project", "p")], "查询", limit=2)

        assert len(chunks) == 2
        assert wiki.calls[0]["limit"] == 5  # 每路内部召回深度独立于最终 limit


class TestSourceIsolation:
    async def test_failing_source_is_skipped(self):
        wiki = RecordingSearcher([_hit("w0")])
        material = RecordingSearcher([], error=RuntimeError("sqlite-vec 不可用"))
        retriever = _retriever(wiki=wiki, material=material)

        chunks = await retriever.retrieve(
            [
                _binding("wiki_project", "proj_1"),
                _binding("project_material", "proj_1"),
            ],
            "查询",
        )

        assert [chunk.doc_id for chunk in chunks] == ["w0"]

    async def test_unregistered_source_type_is_skipped(self):
        retriever = _retriever(wiki=RecordingSearcher([_hit("w0")]))

        chunks = await retriever.retrieve(
            [
                _binding("wiki_project", "proj_1"),
                _binding("zotero_collection", "ABCD1234"),
            ],
            "查询",
        )

        assert [chunk.doc_id for chunk in chunks] == ["w0"]

    async def test_duplicate_bindings_search_once(self):
        wiki = RecordingSearcher([_hit("w0")])
        retriever = _retriever(wiki=wiki)
        binding = _binding("wiki_project", "proj_1")

        await retriever.retrieve([binding, binding], "查询")

        assert len(wiki.calls) == 1


class TestQueryPlumbing:
    async def test_vector_sources_get_query_vector(self):
        wiki = RecordingSearcher([])
        specialist = RecordingSearcher([])
        retriever = _retriever(wiki=wiki, specialist=specialist)

        await retriever.retrieve(
            [
                _binding("wiki_project", "proj_1"),
                _binding("specialist_private", "specialist-x"),
            ],
            "查询",
        )

        assert wiki.calls[0]["query_vector"] == [0.5, 0.25]
        assert specialist.calls[0]["query_vector"] == [0.5, 0.25]
        assert specialist.calls[0]["binding"].agent_id == "specialist-x"

    async def test_text_source_gets_query_without_vector(self):
        material = RecordingSearcher([])
        retriever = _retriever(material=material)

        await retriever.retrieve([_binding("project_material", "proj_1")], "查询")

        call = material.calls[0]
        assert call["query"] == "查询"
        assert call["query_vector"] is None

    async def test_embed_failure_skips_only_vector_sources(self):
        async def broken_embed(query: str) -> List[float]:
            raise RuntimeError("嵌入端点不可用")

        material = RecordingSearcher([_hit("m0")])
        wiki = RecordingSearcher([_hit("w0")])
        retriever = KnowledgeRetriever(
            embed_query=broken_embed,
            searchers={
                "wiki_project": wiki,
                "project_material": material,
            },
        )

        chunks = await retriever.retrieve(
            [
                _binding("wiki_project", "proj_1"),
                _binding("project_material", "proj_1"),
            ],
            "查询",
        )

        assert [chunk.doc_id for chunk in chunks] == ["m0"]
        assert wiki.calls == []

    async def test_raw_binding_dicts_are_coerced(self):
        wiki = RecordingSearcher([_hit("w0")])
        retriever = _retriever(wiki=wiki)

        chunks = await retriever.retrieve(
            [
                {
                    "agent_id": "specialist-x",
                    "source_type": "wiki_project",
                    "source_id": "proj_1",
                    "name": "项目 Wiki",
                }
            ],
            "查询",
        )

        assert [chunk.doc_id for chunk in chunks] == ["w0"]
