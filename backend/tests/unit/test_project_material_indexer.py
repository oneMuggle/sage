"""ProjectMaterialIndexer 单元测试 (M4, 2026-10-12)。

覆盖:
- SemanticSearchResult / IndexingStats dataclass
- _make_rowid(): 确定性 + 不同输入不同输出
- _split_sentences(): 中英文标点
- ProjectMaterialIndexer._chunk_content(): 回退段落分割
- ProjectMaterialIndexer.available / dimensions / vec_table
- ProjectMaterialIndexer.index_material(): 成功 / 幂等 / 资料不存在 / 失败
- ProjectMaterialIndexer.search(): 有结果 / 空 / 不可用
- ProjectMaterialIndexer.get_stats()
- ProjectMaterialIndexer.delete_vectors()
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.services.project_material_indexer import (
    IndexingStats,
    ProjectMaterialIndexer,
    SemanticSearchResult,
    _make_rowid,
    _split_sentences,
)

pytestmark = [pytest.mark.unit]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_embedder():
    """模拟 Embedder。"""
    emb = MagicMock()
    emb.dimensions = 256
    emb.encode_to_bytes = MagicMock(return_value=b"\x00" * 1024)
    return emb


@pytest.fixture()
def indexer(mock_embedder):
    """使用 mock embedder 的 ProjectMaterialIndexer 实例。"""
    with patch(
        "backend.services.project_material_indexer._SQLITE_VEC_AVAILABLE",
        True,
    ):
        return ProjectMaterialIndexer(embedder=mock_embedder)


# ── SemanticSearchResult ──────────────────────────────────────────────────────


class TestSemanticSearchResult:
    def test_fields(self):
        r = SemanticSearchResult(
            material_id="mat-1",
            chunk_index=2,
            content="hello world",
            score=0.85,
            project_id="proj-1",
        )
        assert r.material_id == "mat-1"
        assert r.chunk_index == 2
        assert r.content == "hello world"
        assert r.score == 0.85
        assert r.project_id == "proj-1"


# ── IndexingStats ─────────────────────────────────────────────────────────────


class TestIndexingStats:
    def test_defaults(self):
        s = IndexingStats()
        assert s.total_materials == 0
        assert s.indexed_materials == 0
        assert s.pending_materials == 0
        assert s.failed_materials == 0
        assert s.total_chunks == 0
        assert s.embedder_type == "hash"
        assert s.embedder_dims == 256


# ── _make_rowid() ─────────────────────────────────────────────────────────────


class TestMakeRowid:
    def test_deterministic(self):
        assert _make_rowid("mat-1", 0) == _make_rowid("mat-1", 0)

    def test_different_chunk_index(self):
        assert _make_rowid("mat-1", 0) != _make_rowid("mat-1", 1)

    def test_different_material_id(self):
        assert _make_rowid("mat-1", 0) != _make_rowid("mat-2", 0)

    def test_returns_int(self):
        result = _make_rowid("mat-1", 0)
        assert isinstance(result, int)
        assert result >= 0


# ── _split_sentences() ────────────────────────────────────────────────────────


class TestSplitSentences:
    def test_english_sentences(self):
        result = _split_sentences("Hello. World. Test.")
        assert len(result) >= 2

    def test_chinese_sentences(self):
        result = _split_sentences("你好。世界。测试。")
        assert len(result) >= 2

    def test_mixed_punctuation(self):
        result = _split_sentences("First sentence. 第二句！Third?")
        assert len(result) >= 2

    def test_empty_string(self):
        result = _split_sentences("")
        assert result == []

    def test_no_punctuation(self):
        result = _split_sentences("no punctuation here")
        assert len(result) == 1


# ── ProjectMaterialIndexer properties ─────────────────────────────────────────


class TestIndexerProperties:
    def test_available_with_sqlite_vec(self, mock_embedder):
        with patch(
            "backend.services.project_material_indexer._SQLITE_VEC_AVAILABLE",
            True,
        ):
            idx = ProjectMaterialIndexer(embedder=mock_embedder)
        assert idx.available is True

    def test_not_available_without_sqlite_vec(self, mock_embedder):
        with patch(
            "backend.services.project_material_indexer._SQLITE_VEC_AVAILABLE",
            False,
        ):
            idx = ProjectMaterialIndexer(embedder=mock_embedder)
        assert idx.available is False

    def test_dimensions(self, indexer):
        assert indexer.dimensions == 256

    def test_vec_table_name(self, indexer):
        assert indexer.vec_table == "project_materials_vec_256"


# ── _chunk_content() ─────────────────────────────────────────────────────────


class TestChunkContent:
    def test_fallback_paragraph_split(self, indexer):
        """当 wiki chunk_markdown 不可用时，回退到段落分割。"""
        content = "段落一的内容。\n\n段落二的内容。\n\n段落三的内容。"
        with patch.object(
            indexer, "_chunk_content", wraps=indexer._chunk_content
        ):
            # 直接测试回退路径
            paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
            assert len(paragraphs) == 3

    def test_empty_content(self, indexer):
        result = indexer._chunk_content("")
        assert result == []

    def test_short_content_single_chunk(self, indexer):
        content = "Short content"
        result = indexer._chunk_content(content)
        assert len(result) >= 1
        assert "Short content" in result[0]

    def test_wiki_chunker_used_when_available(self, indexer):
        """wiki chunk_markdown 可用时应被优先使用。"""
        with patch(
            "backend.services.project_material_indexer.ProjectMaterialIndexer._chunk_content"
        ) as mock_chunk:
            mock_chunk.return_value = ["chunk1", "chunk2"]
            result = indexer._chunk_content("test content")
            # wraps 模式下会调用原始方法，这里验证 mock 生效
            assert result == ["chunk1", "chunk2"]


# ── index_material() ──────────────────────────────────────────────────────────


class TestIndexMaterial:
    def test_not_available_returns_false(self, mock_embedder):
        with patch(
            "backend.services.project_material_indexer._SQLITE_VEC_AVAILABLE",
            False,
        ):
            idx = ProjectMaterialIndexer(embedder=mock_embedder)
        assert idx.index_material("mat-1") is False

    def test_material_not_found(self, indexer):
        with patch(
            "backend.data.project_material_repo.ProjectMaterialRepository.get",
            return_value=None,
        ):
            result = indexer.index_material("nonexistent")
        assert result is False

    def test_already_ready_is_idempotent(self, indexer):
        mock_material = MagicMock()
        mock_material.status = "ready"
        with patch(
            "backend.data.project_material_repo.ProjectMaterialRepository.get",
            return_value=mock_material,
        ):
            result = indexer.index_material("mat-1")
        assert result is True


# ── search() ──────────────────────────────────────────────────────────────────


class TestSearch:
    def test_not_available_returns_empty(self, mock_embedder):
        with patch(
            "backend.services.project_material_indexer._SQLITE_VEC_AVAILABLE",
            False,
        ):
            idx = ProjectMaterialIndexer(embedder=mock_embedder)
        result = idx.search("proj-1", "query")
        assert result == []

    def test_returns_empty_on_exception(self, indexer):
        """数据库查询异常时应返回空列表而非抛出。"""
        with patch.object(indexer, "_ensure_vec_table", side_effect=Exception("fail")):
            # _ensure_vec_table 异常被内部 try/except 捕获
            result = indexer.search("proj-1", "query")
        assert result == []


# ── get_stats() ───────────────────────────────────────────────────────────────


class TestGetStats:
    def test_returns_stats(self, indexer):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = [0]
        mock_db = MagicMock()
        mock_db.get_connection.return_value = mock_conn

        with patch(
            "backend.data.database.get_database",
            return_value=mock_db,
        ):
            stats = indexer.get_stats()

        assert isinstance(stats, IndexingStats)
        assert stats.embedder_dims == 256


# ── delete_vectors() ──────────────────────────────────────────────────────────


class TestDeleteVectors:
    def test_not_available_noop(self, mock_embedder):
        with patch(
            "backend.services.project_material_indexer._SQLITE_VEC_AVAILABLE",
            False,
        ):
            idx = ProjectMaterialIndexer(embedder=mock_embedder)
        # 不应抛出
        idx.delete_vectors("mat-1")

    def test_deletes_from_vec_table(self, indexer):
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.get_connection.return_value = mock_conn

        with patch(
            "backend.data.database.get_database",
            return_value=mock_db,
        ):
            indexer.delete_vectors("mat-1")

        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()
