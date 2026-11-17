"""附件 RAG 引用页码映射单测（2026-11-15）。"""

import asyncio
import json

import pytest

from backend.services import attachment_context as ac

pytestmark = pytest.mark.unit

PAGE_TEXT = (
    "--- page 1 ---\n"
    "第一页内容，介绍研究背景与目标。\n\n"
    "--- page 2 ---\n"
    "第二页内容，给出系统架构与实验方法。\n\n"
    "--- page 3 ---\n"
    "第三页内容，总结实验结果。"
)


class TestLocateChunkPages:
    def test_single_page_chunk(self):
        assert ac.locate_chunk_pages(PAGE_TEXT, "第二页内容") == (2, 2)

    def test_chunk_spanning_two_pages(self):
        chunk = "第一页内容，介绍研究背景与目标。\n\n--- page 2 ---\n第二页内容"
        assert ac.locate_chunk_pages(PAGE_TEXT, chunk) == (1, 2)

    def test_chunk_without_page_marker_uses_prefix(self):
        assert ac.locate_chunk_pages(PAGE_TEXT, "介绍研究背景与目标") == (1, 1)

    def test_missing_chunk_returns_none(self):
        assert ac.locate_chunk_pages(PAGE_TEXT, "完全不存在的内容") == (None, None)

    def test_text_without_markers_returns_none(self):
        assert ac.locate_chunk_pages("plain text", "plain") == (None, None)


def _seed_index(tmp_path, text: str, chunk_size: int = 40):
    from backend.services.attachment_rag import index_attachment
    from backend.wiki.embeddings import EmbeddingConfig

    async def _post(url, headers, body):
        return json.dumps(
            {"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]} for _ in body["input"]]}
        )

    return asyncio.run(
        index_attachment(
            media_id="med-pages",
            text=text,
            storage_path=tmp_path / "rag" / "attachments.json",
            embed_config=EmbeddingConfig(
                base_url="https://embed.example/v1", api_key="k", model="emb", dim=4
            ),
            http_post=_post,
            target_chunk_size=chunk_size,
        )
    )


class TestRagCitationPages:
    def test_rag_citations_carry_page_span(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ac, "MAX_TEXT_INJECT_CHARS", 40)
        seeded = _seed_index(tmp_path, PAGE_TEXT)
        assert seeded.chunks >= 2

        async def _embed(query, embed_cfg):
            return [[0.1, 0.2, 0.3, 0.4]]

        ctx = asyncio.run(
            ac.build_attachment_context(
                "med-pages",
                full_text=PAGE_TEXT,
                query="内容",
                rag=ac.AttachmentRagOptions(
                    embed={"base_url": "https://embed.example/v1", "api_key": "k", "model": "emb"},
                    top_k=2,
                ),
                store_path=tmp_path / "rag" / "attachments.json",
                query_embedder=_embed,
            )
        )
        assert ctx is not None
        assert ctx.mode == "rag"
        assert ctx.chunks
        assert all(c.page_start is not None for c in ctx.chunks)
        assert all(c.page_end is not None for c in ctx.chunks)
        assert all(c.page_start <= c.page_end for c in ctx.chunks)
