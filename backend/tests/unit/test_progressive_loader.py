"""ProgressiveSkillLoader 单元测试。"""

from __future__ import annotations

import pytest

from backend.skills.progressive_loader import (
    ProgressiveSkillLoader,
    get_progressive_loader,
    reset_progressive_loader,
)


class TestProgressiveSkillLoader:
    """渐进式加载测试。"""

    @pytest.fixture()
    def sample_skills(self):
        return [
            {
                "name": "academic-search",
                "description": "搜索学术论文和文献",
                "when_to_use": "用户需要查找学术论文时",
                "triggers": ["搜索", "论文"],
            },
            {
                "name": "code-review",
                "description": "代码审查和质量检查",
                "when_to_use": "用户提交代码需要审查时",
                "triggers": ["代码", "审查"],
            },
            {
                "name": "unused-skill",
                "description": "很久没用的技能",
                "when_to_use": "几乎不触发",
                "triggers": [],
            },
        ]

    @pytest.mark.asyncio()
    async def test_build_context_empty_skills(self):
        loader = ProgressiveSkillLoader()
        ctx = await loader.build_context([])
        assert ctx.initial_context == "(无可用技能)"
        assert ctx.hot_skills == []
        assert ctx.cold_count == 0

    @pytest.mark.asyncio()
    async def test_build_context_without_scoring(self, sample_skills):
        """无评分服务时全部归为 warm。"""
        loader = ProgressiveSkillLoader(scoring_service=None)
        ctx = await loader.build_context(sample_skills)
        assert len(ctx.warm_skills) == 3
        assert len(ctx.hot_skills) == 0
        assert ctx.cold_count == 0
        assert "academic-search" in ctx.initial_context

    @pytest.mark.asyncio()
    async def test_build_context_respects_budget(self, sample_skills):
        """上下文应在 token 预算内。"""
        loader = ProgressiveSkillLoader(context_budget_tokens=50)
        ctx = await loader.build_context(sample_skills)
        assert ctx.estimated_tokens <= 60  # 允许一定误差

    def test_load_full_skill(self):
        loader = ProgressiveSkillLoader()
        result = loader.load_full_skill("test-skill", "SKILL.md content here")
        assert "test-skill" in result
        assert "SKILL.md content here" in result

    def test_search_cold_skills(self, sample_skills):
        loader = ProgressiveSkillLoader()
        results = loader.search_cold_skills("论文", sample_skills)
        assert len(results) >= 1
        assert results[0]["name"] == "academic-search"

    def test_search_cold_skills_empty_query(self, sample_skills):
        loader = ProgressiveSkillLoader()
        results = loader.search_cold_skills("", sample_skills)
        assert results == []

    def test_search_cold_skills_top_k(self, sample_skills):
        loader = ProgressiveSkillLoader()
        results = loader.search_cold_skills("代码 审查", sample_skills, top_k=1)
        assert len(results) == 1

    def test_estimate_tokens(self):
        assert ProgressiveSkillLoader._estimate_tokens("hello") >= 1
        assert ProgressiveSkillLoader._estimate_tokens("a" * 300) == 100


class TestSingleton:
    """单例管理测试。"""

    def test_get_returns_instance(self):
        reset_progressive_loader()
        loader = get_progressive_loader()
        assert isinstance(loader, ProgressiveSkillLoader)

    def test_reset_clears(self):
        reset_progressive_loader()
        l1 = get_progressive_loader()
        reset_progressive_loader()
        l2 = get_progressive_loader()
        assert l1 is not l2
