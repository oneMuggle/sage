"""SkillEvolutionService 单元测试。"""

from __future__ import annotations

import pytest

from backend.skills.evolution import (
    EvolutionTrigger,
    EvolutionType,
    SkillEvolutionService,
    SkillFeedbackStore,
    get_evolution_service,
    get_feedback_store,
    reset_evolution_service,
)


class TestEvolutionService:
    """进化服务测试。"""

    @pytest.mark.asyncio()
    async def test_no_trigger_insufficient_usage(self):
        """使用次数不足时不触发。"""
        service = SkillEvolutionService()
        proposal = await service.check_and_evolve(
            "test-skill",
            stats={"use_count": 3, "success_count": 1, "fail_count": 2},
        )
        assert proposal is None

    @pytest.mark.asyncio()
    async def test_trigger_low_success_rate(self):
        """低成功率触发演化。"""
        service = SkillEvolutionService()
        proposal = await service.check_and_evolve(
            "test-skill",
            stats={
                "use_count": 10,
                "success_count": 3,
                "fail_count": 7,
                "user_satisfaction": 0.8,
            },
        )
        assert proposal is not None
        assert proposal.trigger == EvolutionTrigger.LOW_SUCCESS_RATE
        assert proposal.evolution_type == EvolutionType.REVISE_CONTENT
        assert "成功率" in proposal.reason

    @pytest.mark.asyncio()
    async def test_trigger_low_satisfaction(self):
        """低满意度触发演化。"""
        service = SkillEvolutionService()
        proposal = await service.check_and_evolve(
            "test-skill",
            stats={
                "use_count": 15,
                "success_count": 12,
                "fail_count": 3,
                "user_satisfaction": 0.3,
            },
        )
        assert proposal is not None
        assert proposal.trigger == EvolutionTrigger.LOW_SATISFACTION
        assert proposal.evolution_type == EvolutionType.REVISE_DESCRIPTION

    @pytest.mark.asyncio()
    async def test_no_trigger_healthy(self):
        """健康技能不触发。"""
        service = SkillEvolutionService()
        proposal = await service.check_and_evolve(
            "test-skill",
            stats={
                "use_count": 20,
                "success_count": 18,
                "fail_count": 2,
                "user_satisfaction": 0.9,
            },
        )
        assert proposal is None

    @pytest.mark.asyncio()
    async def test_proposal_to_dict(self):
        """proposal 序列化。"""
        service = SkillEvolutionService()
        proposal = await service.check_and_evolve(
            "test-skill",
            stats={"use_count": 10, "success_count": 2, "fail_count": 8},
        )
        assert proposal is not None
        d = proposal.to_dict()
        assert d["skill_name"] == "test-skill"
        assert d["trigger"] == "low_success_rate"
        assert isinstance(d["created_at"], int)


class TestFeedbackStore:
    """反馈存储测试。"""

    def test_record_and_stats(self):
        store = SkillFeedbackStore()
        store.record("skill-a", {"success": True, "token_cost": 100})
        store.record("skill-a", {"success": False, "token_cost": 200})
        store.record("skill-a", {"success": True, "token_cost": 100})

        stats = store.get_stats("skill-a")
        assert stats["use_count"] == 3
        assert stats["success_count"] == 2
        assert stats["fail_count"] == 1
        assert stats["avg_token_cost"] == pytest.approx(133.33, rel=0.1)

    def test_empty_stats(self):
        store = SkillFeedbackStore()
        stats = store.get_stats("nonexistent")
        assert stats == {}

    def test_satisfaction(self):
        store = SkillFeedbackStore()
        store.record("skill-a", {"success": True, "user_thumbs": True})
        store.record("skill-a", {"success": True, "user_thumbs": False})
        stats = store.get_stats("skill-a")
        assert stats["user_satisfaction"] == 0.5

    def test_recent_errors(self):
        store = SkillFeedbackStore()
        store.record("skill-a", {"success": False, "error": "timeout"})
        store.record("skill-a", {"success": True})
        store.record("skill-a", {"success": False, "error": "permission denied"})

        errors = store.get_recent_errors("skill-a")
        assert "timeout" in errors
        assert "permission denied" in errors
        assert len(errors) == 2


class TestSingleton:
    """单例管理测试。"""

    def test_get_evolution_service(self):
        reset_evolution_service()
        service = get_evolution_service()
        assert isinstance(service, SkillEvolutionService)

    def test_get_feedback_store(self):
        reset_evolution_service()
        store = get_feedback_store()
        assert isinstance(store, SkillFeedbackStore)

    def test_reset(self):
        reset_evolution_service()
        s1 = get_evolution_service()
        reset_evolution_service()
        s2 = get_evolution_service()
        assert s1 is not s2
