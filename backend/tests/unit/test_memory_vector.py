"""验证 HashEmbedder 和 VectorStore。"""

import struct
import tempfile

import pytest

from backend.data.database import Database
from backend.memory.embedder import HashEmbedder
from backend.memory.vector_store import VectorStore

pytestmark = pytest.mark.unit


# ==================== HashEmbedder 测试 ====================


class TestHashEmbedder:
    def test_encode_returns_correct_dimensions(self):
        emb = HashEmbedder(dimensions=128)
        vec = emb.encode("测试文本")
        assert len(vec) == 128

    def test_encode_empty_text_returns_zero_vector(self):
        emb = HashEmbedder(dimensions=64)
        vec = emb.encode("")
        assert len(vec) == 64
        assert all(v == 0.0 for v in vec)

    def test_encode_is_deterministic(self):
        emb = HashEmbedder(dimensions=256)
        v1 = emb.encode("相同文本")
        v2 = emb.encode("相同文本")
        assert v1 == v2

    def test_similar_texts_have_close_vectors(self):
        """相似的文本（共享 n-gram）应有较小的距离。"""
        emb = HashEmbedder(dimensions=256)
        v1 = emb.encode("用户喜欢火锅")
        v2 = emb.encode("用户爱吃火锅")
        v3 = emb.encode("今天天气真好")

        # 计算欧氏距离（向量已 L2 归一化）
        d_similar = sum((a - b) ** 2 for a, b in zip(v1, v2, strict=False)) ** 0.5
        d_different = sum((a - b) ** 2 for a, b in zip(v1, v3, strict=False)) ** 0.5

        # 相似文本的距离应小于不同文本
        assert d_similar < d_different

    def test_encode_to_bytes_returns_correct_size(self):
        emb = HashEmbedder(dimensions=256)
        b = emb.encode_to_bytes("测试")
        assert len(b) == 256 * 4  # float32 = 4 bytes

    def test_encode_to_bytes_is_valid_float32(self):
        emb = HashEmbedder(dimensions=32)
        b = emb.encode_to_bytes("测试")
        values = struct.unpack("<32f", b)
        assert len(values) == 32
        assert all(isinstance(v, float) for v in values)


# ==================== VectorStore 测试 ====================


@pytest.fixture()
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
        yield db
        db.close()


@pytest.fixture()
def store(tmp_db):
    return VectorStore(tmp_db, HashEmbedder(dimensions=128))


class TestVectorStore:
    def test_add_and_count(self, store):
        assert store.count() == 0
        store.add("m1", "文本A")
        assert store.count() == 1
        store.add("m2", "文本B")
        assert store.count() == 2

    def test_add_is_idempotent(self, store):
        """同 ID 重复添加应覆盖而非重复。"""
        store.add("m1", "原始文本")
        store.add("m1", "更新文本")
        assert store.count() == 1

    def test_search_returns_results(self, store):
        store.add("m1", "用户喜欢火锅")
        store.add("m2", "Python 编程语言")
        store.add("m3", "周末去爬山")

        results = store.search("火锅", top_k=3)
        assert len(results) == 3
        # 第一个结果应该是距离最小的
        assert results[0]["distance"] <= results[1]["distance"]

    def test_search_with_memory_type_filter(self, store):
        store.add("m1", "火锅", memory_type="episodic")
        store.add("m2", "火锅", memory_type="semantic")

        results = store.search("火锅", top_k=5, memory_type="episodic")
        assert len(results) == 1
        assert results[0]["memory_type"] == "episodic"

    def test_search_empty_store_returns_empty(self, store):
        results = store.search("任何查询")
        assert results == []

    def test_delete_existing(self, store):
        store.add("m1", "要删除的文本")
        assert store.count() == 1
        assert store.delete("m1") is True
        assert store.count() == 0

    def test_delete_nonexistent(self, store):
        assert store.delete("不存在") is False

    def test_result_contains_memory_id_and_distance(self, store):
        store.add("m1", "测试文本")
        results = store.search("测试")
        assert len(results) == 1
        assert "memory_id" in results[0]
        assert "distance" in results[0]
        assert "memory_type" in results[0]
        assert results[0]["memory_id"] == "m1"
