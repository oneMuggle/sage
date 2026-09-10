"""VectorStore 维度迁移与向量回填测试

覆盖:
- _available=False（扩展加载失败）时 add/search/count/backfill 全部 no-op
- 存量表维度与 embedder 不一致 → DROP + 重建（维度迁移）
- pending_backfill_count / backfill_from_tables 的回填语义
"""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock

import pytest

from backend.data.database import Database
from backend.memory.embedder import HashEmbedder
from backend.memory.vector_store import VectorStore

pytestmark = pytest.mark.unit


@pytest.fixture()
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
        yield db
        db.close()


def _insert_episodic(db, memory_id: str, content: str) -> None:
    db.get_connection().execute(
        "INSERT INTO memories_episodic (id, content, created_at) VALUES (?, ?, ?)",
        (memory_id, content, 1700000000),
    )


def _insert_semantic(db, memory_id: str, content: str) -> None:
    db.get_connection().execute(
        "INSERT INTO memories_semantic (id, content, created_at) VALUES (?, ?, ?)",
        (memory_id, content, 1700000000),
    )


class TestUnavailableNoOp:
    def test_extension_load_failure_disables_store(self, tmp_db, monkeypatch):
        """sqlite-vec 加载失败 → _available=False, 各操作安全 no-op"""
        import backend.memory.vector_store as vs_mod

        monkeypatch.setattr(
            vs_mod.sqlite_vec, "load", MagicMock(side_effect=RuntimeError("no ext"))
        )
        store = VectorStore(tmp_db, HashEmbedder(dimensions=64))
        assert store._available is False
        store.add("m1", "text")
        assert store.search("text") == []
        assert store.count() == 0
        assert store.pending_backfill_count() == 0
        assert store.backfill_from_tables() == 0


class TestDimensionMigration:
    def test_dimension_change_recreates_table(self, tmp_db):
        """维度变更: 存量 64 维表 → 128 维 embedder, 表重建且向量清零"""
        store64 = VectorStore(tmp_db, HashEmbedder(dimensions=64))
        store64.add("m1", "文本A")
        assert store64.count() == 1

        # 换维度 embedder 重新打开同一个 DB
        store128 = VectorStore(tmp_db, HashEmbedder(dimensions=128))
        assert store128.dimensions == 128
        assert store128.count() == 0
        assert store128._available is True

    def test_same_dimension_keeps_table(self, tmp_db):
        """维度一致: 重新打开保留既有向量"""
        store = VectorStore(tmp_db, HashEmbedder(dimensions=64))
        store.add("m1", "文本A")
        reopened = VectorStore(tmp_db, HashEmbedder(dimensions=64))
        assert reopened.count() == 1


class TestBackfill:
    def test_pending_and_backfill(self, tmp_db):
        """主表有记忆、向量表为空 → pending>0; backfill 后归零"""
        _insert_episodic(tmp_db, "e1", "用户喜欢火锅")
        _insert_episodic(tmp_db, "e2", "Python 编程")
        _insert_semantic(tmp_db, "s1", "用户偏好简洁回复")

        store = VectorStore(tmp_db, HashEmbedder(dimensions=64))
        assert store.pending_backfill_count() == 3

        done = store.backfill_from_tables(limit=10)
        assert done == 3
        assert store.pending_backfill_count() == 0
        assert store.count() == 3

    def test_backfill_respects_limit(self, tmp_db):
        for i in range(5):
            _insert_episodic(tmp_db, f"e{i}", f"记忆 {i}")
        store = VectorStore(tmp_db, HashEmbedder(dimensions=64))
        done = store.backfill_from_tables(limit=2)
        assert done == 2
        assert store.pending_backfill_count() == 3

    def test_backfill_skips_newest_incremental_adds(self, tmp_db):
        """已建向量的记忆不重复回填（幂等）"""
        store = VectorStore(tmp_db, HashEmbedder(dimensions=64))
        _insert_episodic(tmp_db, "e1", "文本")
        store.add("e1", "文本")
        assert store.backfill_from_tables() == 0

    def test_backfill_stops_on_embedder_error(self, tmp_db, monkeypatch):
        """编码失败（如熔断）时终止本轮, 已回填数保留"""
        store = VectorStore(tmp_db, HashEmbedder(dimensions=64))
        _insert_episodic(tmp_db, "e1", "文本")

        def raise_batch(texts):
            raise RuntimeError("endpoint down")

        monkeypatch.setattr(store._embedder, "encode_batch", raise_batch)
        assert store.backfill_from_tables() == 0
