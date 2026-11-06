"""M2-Task 1 — 专家私有知识向量库测试。

``specialist_vectorstore`` 复用 wiki 的 JSON ``VectorStore``，为每个专家
提供独立命名空间:

    $SAGE_SPECIALISTS_DIR/<agent_id>/vectors.json

page_path 约定 ``specialist-knowledge/<relative_path>``，同一专家内重复
索引幂等替换，不同专家互不可见。嵌入调用通过注入的 ``http_post``
fake（与 ``test_attachment_rag.py`` 同口径），无需真实网络。
"""

import json
import os

import pytest

from backend.agents.specialist_vectorstore import (
    SPECIALIST_KNOWLEDGE_PAGE_PREFIX,
    SpecialistVectorStoreError,
    index_specialist_document,
    remove_specialist_document,
    search_specialist_private,
    specialist_page_path,
    specialist_vectors_path,
)
from backend.wiki.embeddings import EmbeddingConfig

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        os.name == "nt",
        reason="专家私有库复用 wiki VectorStore，依赖 POSIX no-follow 原语",
    ),
]

DIM = 4


@pytest.fixture(autouse=True)
def isolated_specialists_root(tmp_path, monkeypatch):
    """把 ``~/.sage/specialists`` 隔离到 tmp_path。"""
    root = tmp_path / "specialists"
    root.mkdir()
    monkeypatch.setenv("SAGE_SPECIALISTS_DIR", str(root))
    return root


def _make_config(dim: int = DIM) -> EmbeddingConfig:
    return EmbeddingConfig(
        base_url="https://embed.example/v1",
        api_key="k-test",
        model="text-embedding-test",
        dim=dim,
    )


def _fake_http_post(vectors):
    async def _post(url, headers, body):
        assert url.endswith("/embeddings")
        assert headers["Authorization"] == "Bearer k-test"
        count = len(body["input"])
        return json.dumps({"data": [{"embedding": v} for v in vectors[:count]]})

    return _post


async def _index(agent_id: str, text: str, rel_path: str = "style-guide.md", **overrides):
    kwargs = {
        "agent_id": agent_id,
        "rel_path": rel_path,
        "text": text,
        "embed_config": _make_config(),
        "http_post": _fake_http_post([[0.1, 0.2, 0.3, 0.4]] * 8),
    }
    kwargs.update(overrides)
    return await index_specialist_document(**kwargs)


class TestPaths:
    def test_vectors_path_lives_under_isolated_root(self, isolated_specialists_root):
        assert specialist_vectors_path("sp_writer") == (
            isolated_specialists_root / "sp_writer" / "vectors.json"
        )

    @pytest.mark.parametrize("agent_id", ["", ".hidden", "../evil", "a/b", "a\\b"])
    def test_vectors_path_rejects_unsafe_agent_ids(self, agent_id):
        with pytest.raises(SpecialistVectorStoreError):
            specialist_vectors_path(agent_id)

    def test_page_path_prefixes_and_normalizes_backslashes(self):
        assert specialist_page_path("notes\\a.md") == f"{SPECIALIST_KNOWLEDGE_PAGE_PREFIX}notes/a.md"

    @pytest.mark.parametrize("rel_path", ["", "../x.md", "/etc/passwd", "a/../b.md"])
    def test_page_path_rejects_traversal_and_absolute_paths(self, rel_path):
        with pytest.raises(SpecialistVectorStoreError):
            specialist_page_path(rel_path)


class TestIndexSearchDelete:
    async def test_index_then_search_roundtrip(self, isolated_specialists_root):
        text = "第一段内容。\n\n第二段内容，足够长以形成独立分块。\n\n" * 2
        result = await _index("sp_writer", text)

        assert result.agent_id == "sp_writer"
        assert result.page_path == "specialist-knowledge/style-guide.md"
        assert result.chunks > 0
        storage = isolated_specialists_root / "sp_writer" / "vectors.json"
        assert storage.exists()

        hits = search_specialist_private(
            agent_id="sp_writer", query_vector=[0.1, 0.2, 0.3, 0.4]
        )
        assert hits
        assert all(h.page_path == result.page_path for h in hits)

    async def test_two_experts_stay_isolated(self, isolated_specialists_root):
        await _index("sp_a", "甲的私有资料段落。", rel_path="notes.md")
        await _index(
            "sp_b",
            "乙的私有资料段落。",
            rel_path="notes.md",
            http_post=_fake_http_post([[0.9, 0.9, 0.9, 0.9]] * 8),
        )

        hits_a = search_specialist_private(agent_id="sp_a", query_vector=[0.9, 0.9, 0.9, 0.9])
        hits_b = search_specialist_private(agent_id="sp_b", query_vector=[0.9, 0.9, 0.9, 0.9])

        assert hits_a
        assert hits_b
        assert "甲" in hits_a[0].content
        assert "乙" in hits_b[0].content
        assert hits_a[0].content not in [h.content for h in hits_b]

    async def test_reindex_is_idempotent(self, isolated_specialists_root):
        text = "段落。\n\n" * 5
        first = await _index("sp_writer", text)
        second = await _index("sp_writer", text)

        hits = search_specialist_private(
            agent_id="sp_writer", query_vector=[0.1, 0.2, 0.3, 0.4], limit=100
        )
        assert second.chunks == first.chunks == len(hits)  # 替换而非追加

    async def test_empty_text_does_not_create_store(self, isolated_specialists_root):
        result = await _index("sp_writer", "   \n  ")

        assert result.chunks == 0
        assert not (isolated_specialists_root / "sp_writer" / "vectors.json").exists()

    async def test_search_without_store_returns_empty(self):
        assert search_specialist_private(agent_id="sp_unknown", query_vector=[1.0, 0.0, 0.0, 0.0]) == []

    async def test_remove_document(self, isolated_specialists_root):
        await _index("sp_writer", "待删除的知识段落。")

        removed = remove_specialist_document(agent_id="sp_writer", rel_path="style-guide.md")

        assert removed > 0
        assert search_specialist_private(
            agent_id="sp_writer", query_vector=[0.1, 0.2, 0.3, 0.4]
        ) == []
        assert remove_specialist_document(agent_id="sp_writer", rel_path="style-guide.md") == 0

    async def test_embed_http_error_raises_domain_error(self, isolated_specialists_root):
        async def _boom(url, headers, body):
            raise RuntimeError("connection refused")

        with pytest.raises(SpecialistVectorStoreError, match="嵌入请求失败"):
            await _index("sp_writer", "内容段落。", http_post=_boom)

    async def test_dimension_mismatch_raises_domain_error(self, isolated_specialists_root):
        await _index("sp_writer", "先以 dim=4 建立向量库。")

        with pytest.raises(SpecialistVectorStoreError, match="维度"):
            await _index(
                "sp_writer",
                "再以 dim=3 索引应失败。",
                embed_config=_make_config(dim=3),
                http_post=_fake_http_post([[0.1, 0.2, 0.3]] * 8),
            )
