"""r57 — 附件向量索引库层单测。

fake http_post 注入（wiki ingest 同口径），dim=4 小向量验证
索引 / 检索 / 删除全链路与错误面。
"""

import json
from pathlib import Path

import pytest

from backend.services.attachment_rag import (
    AttachmentRagError,
    attachment_page_path,
    index_attachment,
    remove_attachment,
    search_attachments,
)
from backend.wiki.embeddings import EmbeddingConfig
from backend.wiki.vectorstore import VectorStore

pytestmark = pytest.mark.unit

DIM = 4


def _make_config(**overrides) -> EmbeddingConfig:
    defaults = {
        "base_url": "https://embed.example/v1",
        "api_key": "k-test",
        "model": "text-embedding-test",
        "dim": DIM,
    }
    defaults.update(overrides)
    return EmbeddingConfig(**defaults)


def _fake_http_post(vectors):
    """返回固定向量的 http_post（按请求 input 长度切片）。"""
    async def _post(url, headers, body):
        assert url.endswith("/embeddings")
        assert headers["Authorization"] == "Bearer k-test"
        count = len(body["input"])
        return json.dumps({"data": [{"embedding": v} for v in vectors[:count]]})

    return _post


async def _index(tmp_path: Path, text: str, media_id: str = "med-1"):
    return await index_attachment(
        media_id=media_id,
        text=text,
        storage_path=tmp_path / "rag" / "attachments.json",
        embed_config=_make_config(),
        http_post=_fake_http_post([[0.1, 0.2, 0.3, 0.4]] * 8),
    )


class TestIndexAttachment:
    async def test_index_then_search_roundtrip(self, tmp_path):
        text = "第一段内容。\n\n" + "第二段内容，足够长以形成独立分块。\n\n" * 3
        result = await _index(tmp_path, text)
        assert result.chunks > 0
        assert result.page_path == "chat-attachment/med-1"

        storage = tmp_path / "rag" / "attachments.json"
        hits = search_attachments(
            query_vector=[0.1, 0.2, 0.3, 0.4],
            storage_path=storage,
            dim=DIM,
        )
        assert len(hits) >= 1
        assert all(h.page_path == "chat-attachment/med-1" for h in hits)

    async def test_reindex_is_idempotent(self, tmp_path):
        text = "段落。\n\n" * 5
        await _index(tmp_path, text)
        result = await _index(tmp_path, text)
        storage = tmp_path / "rag" / "attachments.json"
        hits = search_attachments(
            query_vector=[0.1, 0.2, 0.3, 0.4], storage_path=storage, dim=DIM, limit=100
        )
        assert result.chunks == len(hits)  # 替换而非追加

    async def test_empty_text_indexes_zero_chunks_without_store(self, tmp_path):
        result = await _index(tmp_path, "   \n  ")
        assert result.chunks == 0
        assert not (tmp_path / "rag" / "attachments.json").exists()

    async def test_embed_http_error_raises_domain_error(self, tmp_path):
        async def _boom(url, headers, body):
            raise RuntimeError("connection refused")

        with pytest.raises(AttachmentRagError, match="嵌入请求失败"):
            await index_attachment(
                media_id="med-err",
                text="内容。\n\n内容。",
                storage_path=tmp_path / "attachments.json",
                embed_config=_make_config(),
                http_post=_boom,
            )

    async def test_vector_count_mismatch_raises(self, tmp_path):
        with pytest.raises(AttachmentRagError, match="嵌入数量"):
            await index_attachment(
                media_id="med-mm",
                text="甲段落。\n\n乙段落。\n\n丙段落。",
                storage_path=tmp_path / "attachments.json",
                embed_config=_make_config(),
                http_post=_fake_http_post([[0.1, 0.2, 0.3, 0.4]] * 1),  # 只回 1 条
                target_chunk_size=10,  # 3 段 → 多分块，与 1 条向量不符
            )

    async def test_bad_embed_body_raises_domain_error(self, tmp_path):
        async def _garbage(url, headers, body):
            return "not-json"

        with pytest.raises(AttachmentRagError, match="嵌入响应不可解析|嵌入请求失败"):
            await index_attachment(
                media_id="med-bad",
                text="内容。\n\n内容。",
                storage_path=tmp_path / "attachments.json",
                embed_config=_make_config(),
                http_post=_garbage,
            )


class TestSearchAttachments:
    async def test_search_missing_store_returns_empty(self, tmp_path):
        hits = search_attachments(
            query_vector=[0.1, 0.2, 0.3, 0.4],
            storage_path=tmp_path / "nope.json",
            dim=DIM,
        )
        assert hits == []

    async def test_media_ids_filter_narrows_scope(self, tmp_path):
        text = "段落一。\n\n段落二。\n\n段落三。"
        await _index(tmp_path, text, media_id="med-a")
        await _index(tmp_path, text, media_id="med-b")

        storage = tmp_path / "rag" / "attachments.json"
        only_b = search_attachments(
            query_vector=[0.1, 0.2, 0.3, 0.4],
            storage_path=storage,
            dim=DIM,
            limit=10,
            media_ids=["med-b"],
        )
        assert only_b, "范围内应有命中"
        assert all(h.page_path == attachment_page_path("med-b") for h in only_b)


class TestRemoveAttachment:
    async def test_remove_missing_store_returns_zero(self, tmp_path):
        assert (
            remove_attachment(
                media_id="ghost", storage_path=tmp_path / "nope.json", dim=DIM
            )
            == 0
        )

    async def test_remove_then_search_empty(self, tmp_path):
        await _index(tmp_path, "段落。\n\n" * 4)
        storage = tmp_path / "rag" / "attachments.json"
        removed = remove_attachment(media_id="med-1", storage_path=storage, dim=DIM)
        assert removed > 0
        assert (
            search_attachments(
                query_vector=[0.1, 0.2, 0.3, 0.4], storage_path=storage, dim=DIM
            )
            == []
        )


class TestOpenAtPersistence:
    async def test_open_at_roundtrip_survives_reopen(self, tmp_path):
        await _index(tmp_path, "段落。\n\n" * 4)
        storage = tmp_path / "rag" / "attachments.json"
        reopened = VectorStore.open_at(storage, DIM)
        assert reopened.by_page[attachment_page_path("med-1")]

    async def test_open_at_dim_mismatch_raises(self, tmp_path):
        await _index(tmp_path, "段落。\n\n" * 4)
        storage = tmp_path / "rag" / "attachments.json"
        with pytest.raises(ValueError, match="维度不匹配"):
            VectorStore.open_at(storage, 8)
