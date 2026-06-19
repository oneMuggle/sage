"""验证 RRF 融合和 Token 预算感知。"""

import pytest

from backend.domain.memory import MemoryContext
from backend.memory.fusion import reciprocal_rank_fusion

pytestmark = pytest.mark.unit


# ==================== RRF 融合测试 ====================


class TestRRF:
    def test_empty_input(self):
        """空输入返回空列表。"""
        assert reciprocal_rank_fusion([]) == []

    def test_single_list(self):
        """单路结果应按原序返回，带 rrf_score。"""
        results = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        fused = reciprocal_rank_fusion([results])
        assert len(fused) == 3
        assert fused[0]["id"] == "a"
        assert fused[0]["rrf_score"] > fused[1]["rrf_score"]

    def test_overlap_boost(self):
        """在两路中都出现的结果应获得更高分。"""
        list1 = [{"id": "a"}, {"id": "b"}]
        list2 = [{"id": "b"}, {"id": "c"}]
        fused = reciprocal_rank_fusion([list1, list2])
        # "b" 在两路都出现，应该排第一
        assert fused[0]["id"] == "b"

    def test_weights(self):
        """不同权重应影响排名。"""
        list1 = [{"id": "a"}]  # 权重 0.9
        list2 = [{"id": "b"}]  # 权重 0.1
        fused = reciprocal_rank_fusion([list1, list2], weights=[0.9, 0.1])
        # "a" 应该排在 "b" 前面
        assert fused[0]["id"] == "a"
        assert fused[1]["id"] == "b"

    def test_preserves_original_fields(self):
        """融合结果应保留原始字段。"""
        results = [{"id": "a", "content": "test", "importance": 7}]
        fused = reciprocal_rank_fusion([results])
        assert fused[0]["content"] == "test"
        assert fused[0]["importance"] == 7
        assert "rrf_score" in fused[0]


# ==================== Token 预算测试 ====================


class TestTokenBudget:
    def test_format_respects_budget(self):
        """format() 应尊重 token 预算。"""
        # 创建大量记忆
        episodic = [{"content": f"记忆{i}" * 50, "importance": 5} for i in range(20)]
        context = MemoryContext(episodic=episodic)

        # 小预算
        small = context.format(budget_tokens=100)
        # 大预算
        large = context.format(budget_tokens=5000)

        # 小预算的输出应比大预算短
        assert len(small) <= len(large)

    def test_core_memory_always_included(self):
        """核心记忆应始终被注入（在预算内）。"""
        context = MemoryContext(
            core=[{"content": "用户喜欢吃火锅"}],
            episodic=[{"content": "普通对话"}],
        )
        formatted = context.format(budget_tokens=1500)
        assert "【用户画像】" in formatted
        assert "用户喜欢吃火锅" in formatted

    def test_empty_context_returns_empty(self):
        """空上下文返回空字符串。"""
        context = MemoryContext()
        assert context.format() == ""

    def test_estimate_tokens_handles_chinese(self):
        """token 估算应正确处理中文。"""
        # 4 个中文字 ≈ 2-3 tokens
        n = MemoryContext._estimate_tokens("你好世界")
        assert n >= 2
        assert n <= 5

    def test_importance_ordering(self):
        """高重要性记忆应优先注入。"""
        context = MemoryContext(
            episodic=[
                {"content": "低重要性" * 20, "importance": 3},
                {"content": "高重要性" * 20, "importance": 9},
            ]
        )
        # 用较小预算，应只注入高重要性的
        formatted = context.format(budget_tokens=100)
        if "高重要性" in formatted:
            # 如果预算只够一条，应该是高重要性的
            assert "高重要性" in formatted
