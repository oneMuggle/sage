"""记忆召回优化: 软过滤 session 策略 + 动态 core 槽位预算测试。

覆盖 PR feat/memory-recall-optimization:
- VectorStore.search(soft_filter=True) 跨会话召回 + 过取 top_k*3
- MemoryAdapter.retrieve() 同会话加分 1.5x / 跨会话降分 0.7x
- 动态 core 槽位预算 (fused 多时放宽到 3)
"""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock

import pytest

from backend.adapters.out.memory.adapter import MemoryAdapter
from backend.data.database import Database
from backend.memory.embedder import HashEmbedder, OnnxEmbedder
from backend.memory.vector_store import VectorStore

pytestmark = pytest.mark.unit


# ==================== VectorStore.soft_filter ====================


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


class TestVectorStoreSoftFilter:
    def test_soft_filter_returns_cross_session_results(self, store):
        """soft_filter=True 时不按 session 严格过滤, 跨会话记忆可召回。"""
        store.add("a1", "用户喜欢火锅", session_id="sess-A")
        store.add("b1", "用户爱吃火锅", session_id="sess-B")

        results = store.search("火锅", top_k=5, session_id="sess-A", soft_filter=True)
        assert sorted(r["memory_id"] for r in results) == ["a1", "b1"]

    def test_soft_filter_overfetches_beyond_top_k(self, store):
        """软过滤模式过取 top_k*3 条, 交由调用方按 session 加权后排序。"""
        for i in range(10):
            session = "sess-A" if i < 2 else "sess-B"
            store.add(f"m{i}", f"火锅条目 {i}", session_id=session)

        results = store.search("火锅", top_k=2, session_id="sess-A", soft_filter=True)
        assert len(results) == 6  # top_k * 3 过取

    def test_soft_filter_without_session_id_behaves_like_normal(self, store):
        """soft_filter=True 但 session_id 为 None 时退化为普通 KNN。"""
        store.add("n1", "通用向量")
        store.add("n2", "另一条")

        soft = store.search("通用", top_k=5, session_id=None, soft_filter=True)
        strict = store.search("通用", top_k=5, session_id=None, soft_filter=False)
        assert [r["memory_id"] for r in soft] == [r["memory_id"] for r in strict]

    def test_default_soft_filter_is_false(self, store):
        """默认值 false —— 旧调用方行为不变 (严格 session 隔离)。"""
        store.add("a1", "用户喜欢火锅", session_id="sess-A")
        store.add("b1", "用户爱吃火锅", session_id="sess-B")

        results = store.search("火锅", top_k=5, session_id="sess-A")
        assert [r["memory_id"] for r in results] == ["a1"]


# ==================== MemoryAdapter session 加权 ====================


def _make_adapter_with_vectors(embedder, vec_hits, keyword_hits=None):
    """构造带 Mock 向量库的 MemoryAdapter。"""
    memory_manager = MagicMock()
    memory_manager.recall.return_value = {
        "working": [],
        "episodic": keyword_hits if keyword_hits is not None else [],
        "semantic": [],
    }

    rows = {hit["memory_id"]: dict(hit) for hit in vec_hits}
    memory_manager.episodic.get_by_id.side_effect = lambda mid: rows.get(mid)
    memory_manager.semantic.get_by_id.return_value = None

    vector_store = MagicMock()
    vector_store.search.return_value = vec_hits

    adapter = MemoryAdapter.__new__(MemoryAdapter)
    adapter.memory_manager = memory_manager
    adapter.embedder = embedder
    adapter.vector_store = vector_store
    adapter.user_profile = None
    return adapter, memory_manager, vector_store


class TestAdapterSessionBoost:
    @pytest.mark.asyncio()
    async def test_same_session_gets_higher_rrf_score_than_cross_session(self):
        """同一条内容, 同会话记忆的 rrf_score 应高于跨会话。"""
        same = {"memory_id": "same", "session_id": "s1", "distance": 0.1, "importance": 5}
        cross = {"memory_id": "cross", "session_id": "s2", "distance": 0.1, "importance": 5}
        adapter, _, _ = _make_adapter_with_vectors(
            OnnxEmbedder(model_dir="/tmp/unused"), [same, cross]
        )

        captured = {}
        from backend.memory import fusion as fusion_mod

        def fake_fusion(lists, weights=None, k=60):
            captured["vec"] = lists[1]
            return []

        original = fusion_mod.reciprocal_rank_fusion
        fusion_mod.reciprocal_rank_fusion = fake_fusion
        try:
            await adapter.retrieve("query", "s1")
        finally:
            fusion_mod.reciprocal_rank_fusion = original

        scores = {item["memory_id"]: item["rrf_score"] for item in captured["vec"]}
        assert scores["same"] > scores["cross"]
        assert scores["same"] / scores["cross"] == pytest.approx(1.5 / 0.7)

    @pytest.mark.asyncio()
    async def test_adapter_passes_soft_filter_true(self):
        """adapter 必须以 soft_filter=True 调向量库, 否则跨会话仍被 SQL 挡掉。"""
        adapter, _, vector_store = _make_adapter_with_vectors(
            OnnxEmbedder(model_dir="/tmp/unused"), []
        )
        from backend.memory import fusion as fusion_mod

        original = fusion_mod.reciprocal_rank_fusion
        fusion_mod.reciprocal_rank_fusion = lambda lists, weights=None, k=60: []
        try:
            await adapter.retrieve("query", "s1")
        finally:
            fusion_mod.reciprocal_rank_fusion = original

        assert vector_store.search.call_args.kwargs["soft_filter"] is True

    @pytest.mark.asyncio()
    async def test_missing_memory_row_is_skipped(self):
        """向量命中但主表已无该行时不应崩, 直接跳过。"""
        orphan = {"memory_id": "gone", "session_id": "s1", "distance": 0.1}
        adapter, memory_manager, _ = _make_adapter_with_vectors(
            OnnxEmbedder(model_dir="/tmp/unused"), [orphan]
        )
        memory_manager.episodic.get_by_id.side_effect = None
        memory_manager.episodic.get_by_id.return_value = None

        from backend.memory import fusion as fusion_mod

        captured = {}
        original = fusion_mod.reciprocal_rank_fusion

        def fake_fusion(lists, weights=None, k=60):
            captured["vec"] = lists[1]
            return []

        fusion_mod.reciprocal_rank_fusion = fake_fusion
        try:
            await adapter.retrieve("query", "s1")
        finally:
            fusion_mod.reciprocal_rank_fusion = original

        assert captured["vec"] == []


# ==================== 动态 core 槽位预算 ====================


def _high_importance(count):
    return [
        {"id": f"hi{i}", "content": "c", "importance": 8, "memory_type": "episodic"}
        for i in range(count)
    ]


def _passthrough_fusion(lists, weights=None, k=60):
    return lists[0] + lists[1]


class TestDynamicCoreBudget:
    @pytest.mark.asyncio()
    async def test_many_hits_widen_core_budget_to_three(self):
        """fused >= 5 时 core 检索槽位放宽到 3。"""
        adapter, _, _ = _make_adapter_with_vectors(
            OnnxEmbedder(model_dir="/tmp/unused"), [], keyword_hits=_high_importance(6)
        )
        from backend.memory import fusion as fusion_mod

        original = fusion_mod.reciprocal_rank_fusion
        fusion_mod.reciprocal_rank_fusion = _passthrough_fusion
        try:
            context = await adapter.retrieve("query", "s1")
        finally:
            fusion_mod.reciprocal_rank_fusion = original

        assert len(context.core) == 3

    @pytest.mark.asyncio()
    async def test_few_hits_narrow_core_budget_to_two(self):
        """fused 在 [2,4) 时 core 检索槽位为 2。"""
        adapter, _, _ = _make_adapter_with_vectors(
            OnnxEmbedder(model_dir="/tmp/unused"), [], keyword_hits=_high_importance(3)
        )
        from backend.memory import fusion as fusion_mod

        original = fusion_mod.reciprocal_rank_fusion
        fusion_mod.reciprocal_rank_fusion = _passthrough_fusion
        try:
            context = await adapter.retrieve("query", "s1")
        finally:
            fusion_mod.reciprocal_rank_fusion = original

        assert len(context.core) == 2

    @pytest.mark.asyncio()
    async def test_single_hit_core_budget_is_one(self):
        """fused 仅 1 条时 core 检索槽位为 1。"""
        adapter, _, _ = _make_adapter_with_vectors(
            OnnxEmbedder(model_dir="/tmp/unused"), [], keyword_hits=_high_importance(1)
        )
        from backend.memory import fusion as fusion_mod

        original = fusion_mod.reciprocal_rank_fusion
        fusion_mod.reciprocal_rank_fusion = _passthrough_fusion
        try:
            context = await adapter.retrieve("query", "s1")
        finally:
            fusion_mod.reciprocal_rank_fusion = original

        assert len(context.core) == 1
