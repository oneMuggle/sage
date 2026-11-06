"""M2-Task 4/5 — 专家知识检索注入、引用输出与无命中拒答测试。

覆盖：profile → 绑定的提取、上下文块格式与两级截断、sources_used 条目
形状（``kind="knowledge"`` + loc 字段）、无绑定短路、检索异常 fail-open、
无命中拒答提示（``no_hit_hint``）、日志 span 可观测。
不触碰真实存储：检索器全部注入 fake。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from backend.agents.knowledge_retriever import RetrievedChunk
from backend.chat.specialist_knowledge import (
    KNOWLEDGE_CHUNK_MAX_CHARS,
    KNOWLEDGE_CONTEXT_MAX_CHARS,
    build_knowledge_context,
    knowledge_bindings_from_profile,
    knowledge_sources_from_chunks,
    retrieve_knowledge_context,
)


def _profile(bindings: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {"knowledge_bindings": bindings if bindings is not None else [_binding()]}


def _binding(source_type: str = "wiki_project", source_id: str = "proj_1") -> Dict[str, Any]:
    return {
        "id": "kb_1",
        "agent_id": "specialist-x",
        "source_type": source_type,
        "source_id": source_id,
        "name": "项目 Wiki",
        "filters": {},
        "created_at": 1,
    }


def _chunk(**patch: Any) -> RetrievedChunk:
    base: Dict[str, Any] = {
        "doc_id": "wiki/a.md::0",
        "content": "分层架构说明",
        "score": 0.0166,
        "source_type": "wiki_project",
        "source_id": "proj_1",
        "binding_id": "kb_1",
        "binding_name": "项目 Wiki",
        "agent_id": "specialist-x",
        "loc": {"page_path": "wiki/a.md", "chunk_index": 0},
    }
    base.update(patch)
    return RetrievedChunk(**base)


class RecordingRetriever:
    """记录调用并返回预设结果的异步检索器。"""

    def __init__(self, chunks: List[RetrievedChunk], *, error: Optional[Exception] = None):
        self.chunks = chunks
        self.error = error
        self.calls: List[Dict[str, Any]] = []

    async def retrieve(self, bindings: Any, query: str, *, limit: int = 5) -> List[RetrievedChunk]:
        self.calls.append({"bindings": bindings, "query": query, "limit": limit})
        if self.error is not None:
            raise self.error
        return list(self.chunks)


class TestBindingsFromProfile:
    def test_reads_binding_list_from_dict_profile(self):
        bindings = knowledge_bindings_from_profile(_profile())
        assert [b["id"] for b in bindings] == ["kb_1"]

    def test_missing_or_invalid_profile_returns_empty(self):
        assert knowledge_bindings_from_profile(None) == []
        assert knowledge_bindings_from_profile({}) == []
        assert knowledge_bindings_from_profile({"knowledge_bindings": "bad"}) == []
        assert knowledge_bindings_from_profile({"knowledge_bindings": [1, "x"]}) == []


class TestBuildKnowledgeContext:
    def test_empty_chunks_yield_empty_block(self):
        assert build_knowledge_context([]) == ""

    def test_renders_ref_source_loc_and_content(self):
        block = build_knowledge_context([_chunk()])

        assert "<knowledge_context>" in block
        assert "</knowledge_context>" in block
        assert "[K1]" in block
        assert "项目 Wiki" in block
        assert "wiki/a.md" in block
        assert "#0" in block
        assert "分层架构说明" in block

    def test_long_chunk_is_truncated(self):
        block = build_knowledge_context([_chunk(content="字" * (KNOWLEDGE_CHUNK_MAX_CHARS + 100))])

        assert "…" in block
        # 块内正文不超过单块上限（外加元数据行不会把单块撑爆太多）
        assert len(block) < KNOWLEDGE_CHUNK_MAX_CHARS + 300

    def test_total_block_is_capped(self):
        chunks = [
            _chunk(
                doc_id=f"wiki/p{i}.md::0",
                content="内容" * 400,
                loc={"page_path": f"wiki/p{i}.md", "chunk_index": 0},
            )
            for i in range(10)
        ]
        block = build_knowledge_context(chunks)

        assert len(block) <= KNOWLEDGE_CONTEXT_MAX_CHARS
        # 至少保留了第一块（不是整块丢弃）
        assert "[K1]" in block


class TestKnowledgeSources:
    def test_wiki_chunk_maps_to_source_entry(self):
        [source] = knowledge_sources_from_chunks([_chunk()])

        assert source["kind"] == "knowledge"
        assert source["source_type"] == "wiki_project"
        assert source["source_id"] == "proj_1"
        assert source["binding_id"] == "kb_1"
        assert source["binding_name"] == "项目 Wiki"
        assert source["agent_id"] == "specialist-x"
        assert source["title"] == "wiki/a.md"
        assert source["path"] == "wiki/a.md"
        assert source["chunk_index"] == 0
        assert source["score"] == pytest.approx(0.02)
        assert source["loc"] == {"page_path": "wiki/a.md", "chunk_index": 0}
        assert source["snippet"] == "分层架构说明"

    def test_material_chunk_carries_material_and_project(self):
        chunk = _chunk(
            doc_id="mat_9::2",
            source_type="project_material",
            binding_name="项目资料",
            loc={"material_id": "mat_9", "chunk_index": 2, "project_id": "proj_1"},
        )
        [source] = knowledge_sources_from_chunks([chunk])

        assert source["material_id"] == "mat_9"
        assert source["project_id"] == "proj_1"
        assert source["chunk_index"] == 2
        assert source["title"] == "mat_9"
        assert source.get("path") is None

    def test_snippet_is_shortened(self):
        [source] = knowledge_sources_from_chunks([_chunk(content="长" * 500)])
        assert len(source["snippet"]) <= 160
        assert source["snippet"].endswith("…")

    def test_empty_chunks_yield_empty_list(self):
        assert knowledge_sources_from_chunks([]) == []


class TestRetrieveKnowledgeContext:
    pytestmark = pytest.mark.asyncio

    async def test_no_bindings_short_circuits(self):
        retriever = RecordingRetriever([_chunk()])

        block, sources, no_hit_hint = await retrieve_knowledge_context(
            {"knowledge_bindings": []}, "查询", retriever=retriever
        )

        assert block == ""
        assert sources == []
        assert no_hit_hint == ""
        assert retriever.calls == []

    async def test_returns_context_and_sources(self):
        retriever = RecordingRetriever([_chunk()])

        block, sources, no_hit_hint = await retrieve_knowledge_context(
            _profile(), "分层架构?", retriever=retriever
        )

        assert "<knowledge_context>" in block
        assert sources[0]["kind"] == "knowledge"
        assert no_hit_hint == ""
        assert retriever.calls[0]["query"] == "分层架构?"
        assert retriever.calls[0]["bindings"][0]["id"] == "kb_1"

    async def test_retriever_failure_is_fail_open(self):
        retriever = RecordingRetriever([], error=RuntimeError("嵌入端点不可用"))

        block, sources, no_hit_hint = await retrieve_knowledge_context(
            _profile(), "查询", retriever=retriever
        )

        assert block == ""
        assert sources == []
        # 检索异常属 fail-open，不触发拒答提示（避免误拦）
        assert no_hit_hint == ""

    async def test_no_hits_yields_empty(self):
        retriever = RecordingRetriever([])

        block, sources, no_hit_hint = await retrieve_knowledge_context(
            _profile(), "查询", retriever=retriever
        )

        assert block == ""
        assert sources == []
        # M2-Task 5: 有绑定但无命中 → 返回拒答提示
        assert no_hit_hint != ""
        assert "知识库" in no_hit_hint
        assert "无相关内容" in no_hit_hint

    async def test_no_hit_hint_mentions_binding_names(self):
        """拒答提示应包含绑定名，让用户知道查了哪些库。"""
        retriever = RecordingRetriever([])

        _, _, no_hit_hint = await retrieve_knowledge_context(
            _profile(), "查询", retriever=retriever
        )

        assert "项目 Wiki" in no_hit_hint

    async def test_empty_query_no_hit_hint_is_empty(self):
        """空查询不触发拒答（用户还没问问题）。"""
        retriever = RecordingRetriever([])

        _, _, no_hit_hint = await retrieve_knowledge_context(
            _profile(), "", retriever=retriever
        )

        assert no_hit_hint == ""

    async def test_logs_observability_span(self, caplog):
        """M2-Task 5 可观测：命中/无命中/异常均输出 [SPECIALIST_KNOWLEDGE] span。"""
        import logging

        with caplog.at_level(logging.INFO, logger="backend.chat.specialist_knowledge"):
            await retrieve_knowledge_context(
                _profile(), "查询", retriever=RecordingRetriever([_chunk()])
            )
            await retrieve_knowledge_context(
                _profile(), "查询", retriever=RecordingRetriever([])
            )

        spans = [r.message for r in caplog.records if "[SPECIALIST_KNOWLEDGE]" in r.message]
        assert any("status=hit" in m for m in spans)
        assert any("status=no_hit" in m for m in spans)
        assert all("elapsed_ms=" in m for m in spans)

    async def test_logs_error_span_on_retriever_failure(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="backend.chat.specialist_knowledge"):
            await retrieve_knowledge_context(
                _profile(),
                "查询",
                retriever=RecordingRetriever([], error=RuntimeError("boom")),
            )

        spans = [r.message for r in caplog.records if "[SPECIALIST_KNOWLEDGE]" in r.message]
        assert any("status=error" in m for m in spans)
