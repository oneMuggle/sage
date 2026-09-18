"""r66 — producer 附件检索注入决策单测（build_attachment_context）。"""

import asyncio
import json
import pathlib

import pytest

from backend.services.attachment_context import (
    MAX_TEXT_INJECT_CHARS,
    AttachmentRagOptions,
    build_attachment_context,
)

pytestmark = pytest.mark.unit


def _rag(**overrides) -> AttachmentRagOptions:
    defaults = {
        "embed": {"base_url": "https://embed.example/v1", "api_key": "k", "model": "emb"},
        "top_k": 2,
    }
    defaults.update(overrides)
    return AttachmentRagOptions(**defaults)


def _embed_ok(vectors):
    async def _embed(query, embed_cfg):
        return vectors[:1]

    return _embed


def _seed_index(tmp_path: pathlib.Path, chunks):
    """直接用 r57 库层建索引（http_post fake，dim=4）。"""
    from backend.mcp.oauth_store import _default_root  # noqa: F401 — 仅占位对齐命名
    from backend.services.attachment_rag import index_attachment
    from backend.wiki.embeddings import EmbeddingConfig

    async def _post(url, headers, body):
        return json.dumps(
            {"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]} for _ in body["input"]]}
        )

    text = "\n\n".join(
        f"段落{chr(0x4E00 + i)}内容，足够独特以便区分命中。" for i in range(len(chunks))
    )
    return asyncio.run(
        index_attachment(
            media_id="med-1",
            text=text,
            storage_path=tmp_path / "rag" / "attachments.json",
            embed_config=EmbeddingConfig(
                base_url="https://embed.example/v1", api_key="k", model="emb", dim=4
            ),
            http_post=_post,
            target_chunk_size=30,
        )
    )


class TestBuildAttachmentContext:
    def test_short_text_returns_full(self, tmp_path):
        ctx = asyncio.run(
            build_attachment_context(
                "med-1",
                full_text="短文档内容",
                query="q",
                rag=None,
                store_path=tmp_path / "none.json",
            )
        )
        assert ctx == "短文档内容"

    def test_over_limit_without_rag_truncates(self, tmp_path):
        full = "长" * (MAX_TEXT_INJECT_CHARS + 500)
        ctx = asyncio.run(
            build_attachment_context(
                "med-1", full_text=full, query="q", rag=None, store_path=tmp_path / "none.json"
            )
        )
        assert ctx is not None
        assert len(ctx) == MAX_TEXT_INJECT_CHARS

    def test_over_limit_with_rag_and_hits_injects_chunks(self, tmp_path):
        seeded = _seed_index(tmp_path, range(4))
        assert seeded.chunks >= 2
        full = "长" * (MAX_TEXT_INJECT_CHARS + 500)
        ctx = asyncio.run(
            build_attachment_context(
                "med-1",
                full_text=full,
                query="段落",
                rag=_rag(top_k=2),
                store_path=tmp_path / "rag" / "attachments.json",
                query_embedder=_embed_ok([[0.1, 0.2, 0.3, 0.4]]),
            )
        )
        assert ctx is not None
        assert "mode=rag" in ctx
        assert "[chunk" in ctx
        # 含文档开头（head）
        assert "长" * 10 in ctx

    def test_over_limit_rag_no_hits_truncates(self, tmp_path):
        full = "长" * (MAX_TEXT_INJECT_CHARS + 500)
        # 无索引文件 → 检索空 → 回退截断
        ctx = asyncio.run(
            build_attachment_context(
                "med-1",
                full_text=full,
                query="q",
                rag=_rag(),
                store_path=tmp_path / "rag" / "missing.json",
                query_embedder=_embed_ok([[0.1, 0.2, 0.3, 0.4]]),
            )
        )
        assert ctx is not None
        assert len(ctx) == MAX_TEXT_INJECT_CHARS

    def test_embed_failure_falls_back_to_truncate(self, tmp_path):
        full = "长" * (MAX_TEXT_INJECT_CHARS + 500)

        async def _boom(query, embed_cfg):
            raise RuntimeError("embed down")

        ctx = asyncio.run(
            build_attachment_context(
                "med-1",
                full_text=full,
                query="q",
                rag=_rag(),
                store_path=tmp_path / "none.json",
                query_embedder=_boom,
            )
        )
        assert ctx is not None
        assert len(ctx) == MAX_TEXT_INJECT_CHARS

    def test_rag_without_embedder_truncates(self, tmp_path):
        full = "长" * (MAX_TEXT_INJECT_CHARS + 500)
        ctx = asyncio.run(
            build_attachment_context(
                "med-1",
                full_text=full,
                query="q",
                rag=_rag(),
                store_path=tmp_path / "none.json",
                query_embedder=None,
            )
        )
        assert ctx is not None
        assert len(ctx) == MAX_TEXT_INJECT_CHARS
