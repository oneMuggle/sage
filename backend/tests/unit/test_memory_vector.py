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
        d_similar = sum((a - b) ** 2 for a, b in zip(v1, v2)) ** 0.5
        d_different = sum((a - b) ** 2 for a, b in zip(v1, v3)) ** 0.5

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

    def test_search_session_isolation(self, store):
        """spec §4.3 step 5:session_id 过滤必须阻止跨 session 召回。"""
        store.add("a1", "用户喜欢火锅", session_id="sess-A")
        store.add("b1", "用户爱吃火锅", session_id="sess-B")
        store.add("b2", "完全无关的天气", session_id="sess-B")

        # 不传 session_id:跨 session 召回三条（top_k=5 都装得下）
        all_results = store.search("火锅", top_k=5)
        ids_all = sorted(r["memory_id"] for r in all_results)
        assert ids_all == ["a1", "b1", "b2"]

        # 仅 sess-A:只能命中 a1
        a_only = store.search("火锅", top_k=5, session_id="sess-A")
        ids_a = [r["memory_id"] for r in a_only]
        assert ids_a == ["a1"]
        assert all(r["session_id"] == "sess-A" for r in a_only)

        # 仅 sess-B:只剩 b1/b2 属 sess-B
        b_only = store.search("火锅", top_k=5, session_id="sess-B")
        ids_b = sorted(r["memory_id"] for r in b_only)
        assert ids_b == ["b1", "b2"]
        assert all(r["session_id"] == "sess-B" for r in b_only)

        # 不存在的 session_id:无命中
        none_results = store.search("火锅", top_k=5, session_id="sess-X")
        assert none_results == []

    def test_search_session_filter_excludes_all_other_sessions(self, store):
        """session_id 过滤严格隔离:任何非目标 session 行都不能漏出。"""
        store.add("a1", "今天天气好", session_id="sess-A")
        store.add("b1", "明天天气好", session_id="sess-B")
        store.add("c1", "后天天气好", session_id="sess-C")

        only_a = store.search("天气", top_k=10, session_id="sess-A")
        assert {r["memory_id"] for r in only_a} == {"a1"}
        assert all(r["session_id"] == "sess-A" for r in only_a)

    def test_add_persists_session_id_in_result(self, store):
        """add() 写入的 session_id 必须在 search() 结果中可读。"""
        store.add("x", "hello", session_id="sess-X")
        results = store.search("hello", session_id="sess-X")
        assert results[0]["session_id"] == "sess-X"

    def test_search_session_id_none_is_backward_compatible(self, store):
        """未带 session_id 时返回结果不带 session_id 字段错误,
        应仍按 KNN 排序返回全部 (NULL session_id 视为通用向量)。"""
        store.add("n1", "通用向量 1")  # 无 session_id
        results = store.search("通用", top_k=5)
        assert len(results) >= 1
        assert any(r["memory_id"] == "n1" for r in results)
