"""T1 (P10): RRF 权重按嵌入器类型重配 + 检索埋点测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.adapters.out.memory.adapter import MemoryAdapter
from backend.memory.embedder import HashEmbedder, OnnxEmbedder

pytestmark = pytest.mark.unit


def _make_adapter(embedder):
    """构造嵌入器注入 + 其余全 mock 的 MemoryAdapter。"""
    memory_manager = MagicMock()
    memory_manager.episodic.db = None
    memory_manager.recall.return_value = {
        "working": [],
        "episodic": [{"id": "k1", "content": "kw", "importance": 5}],
        "semantic": [],
    }
    memory_manager.episodic.get_by_id.return_value = None
    memory_manager.semantic.get_by_id.return_value = None
    adapter = MemoryAdapter.__new__(MemoryAdapter)
    adapter.memory_manager = memory_manager
    adapter.embedder = embedder
    adapter.vector_store = None
    adapter.user_profile = None
    return adapter


@pytest.mark.asyncio()
async def test_hash_embedder_skips_vector_path():
    """字面哈希嵌入器: 跳向量路, 只用关键词 (哈希向量与关键词路高度重叠)。"""
    adapter = _make_adapter(HashEmbedder(dimensions=256))
    captured = {}

    def fake_fusion(lists, weights=None, k=60):
        captured["weights"] = weights
        return []

    from backend.memory import fusion as fusion_mod

    original = fusion_mod.reciprocal_rank_fusion
    fusion_mod.reciprocal_rank_fusion = fake_fusion
    try:
        await adapter.retrieve("query", "s1")
    finally:
        fusion_mod.reciprocal_rank_fusion = original

    # 融合函数根本不应被调用 —— 走了 skip-vector 分支
    assert captured == {}


@pytest.mark.asyncio()
async def test_hash_embedder_result_is_keyword_only():
    """skip-vector 分支下返回的是关键词路结果本身。"""
    adapter = _make_adapter(HashEmbedder(dimensions=256))

    from backend.memory import fusion as fusion_mod

    original = fusion_mod.reciprocal_rank_fusion
    fusion_mod.reciprocal_rank_fusion = lambda lists, weights=None, k=60: []
    try:
        context = await adapter.retrieve("query", "s1")
    finally:
        fusion_mod.reciprocal_rank_fusion = original

    # 关键词路唯一的 k1 未达 core 门槛 (importance 5 < 8) 且非 semantic/fact
    assert [item["id"] for item in context.episodic] == ["k1"]
    assert context.semantic == []
    assert context.core == []


@pytest.mark.asyncio()
async def test_semantic_embedder_uses_vector_heavy_weights():
    """语义嵌入器: 向量路权重 >= 关键词路 (真语义相似度)。

    A/B 变体按 query 稳定 hash 二分 (A=[0.2,0.8] / B=均权),
    两者都保证向量路不弱于关键词路, 故断言此不变式而非具体数值。
    """
    embedder = OnnxEmbedder(model_dir="/tmp/unused")
    adapter = _make_adapter(embedder)
    captured = {}

    def fake_fusion(lists, weights=None, k=60):
        captured["weights"] = weights
        return []

    from backend.memory import fusion as fusion_mod

    original = fusion_mod.reciprocal_rank_fusion
    fusion_mod.reciprocal_rank_fusion = fake_fusion
    try:
        await adapter.retrieve("query", "s1")
    finally:
        fusion_mod.reciprocal_rank_fusion = original

    assert "weights" in captured
    keyword_w, vector_w = captured["weights"]
    assert vector_w >= keyword_w


@pytest.mark.asyncio()
async def test_retrieval_emits_hit_rate_log(caplog):
    """检索完成后输出命中率观测日志 (keyword/vector/fused 计数)。"""
    adapter = _make_adapter(HashEmbedder(dimensions=256))

    with pytest.MonkeyPatch.context() as mp:
        from backend.memory import fusion as fusion_mod

        mp.setattr(fusion_mod, "reciprocal_rank_fusion", lambda lists, weights=None, k=60: [])
        import logging

        logging.disable(logging.NOTSET)
        with caplog.at_level(logging.INFO, logger="backend.adapters.out.memory.adapter"):
            await adapter.retrieve("query", "s1")

    assert any(
        "[retrieval]" in r.message and "keyword_hits" in r.message
        for r in caplog.records
    )
