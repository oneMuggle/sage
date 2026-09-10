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
async def test_hash_embedder_uses_keyword_heavy_weights():
    """字面哈希嵌入器: 关键词路权重 > 向量路 (哈希向量与关键词路重叠)。"""
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

    assert captured["weights"] == [0.6, 0.4]


@pytest.mark.asyncio()
async def test_semantic_embedder_uses_vector_heavy_weights():
    """语义嵌入器: 向量路权重 > 关键词路 (真语义相似度)。"""
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

    assert captured["weights"] == [0.3, 0.7]


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
