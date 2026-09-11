"""Curator 第三块测试（Round 7: provenance 注入 + 巡检 cron 任务）"""

from __future__ import annotations

import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.data.database import Database
from backend.scheduler.evolution import SkillConsolidationTask
from backend.skills.audit import SkillAuditLog
from backend.skills.consolidator import ConsolidationService
from backend.skills.review_service import ReviewService

pytestmark = pytest.mark.unit


@pytest.fixture()
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
        yield db
        db.close()


def _provider(text: str):
    provider = SimpleNamespace()
    provider.complete = AsyncMock(return_value=SimpleNamespace(text=text))
    return provider


class TestConsolidationTask:
    @pytest.mark.asyncio()
    async def test_records_suggestions_to_audit(self, tmp_db, monkeypatch):
        """巡检产出建议 → consolidation_note 落台账"""
        import backend.skills.consolidator as cons_mod

        fake_service = SimpleNamespace()
        fake_service.scan = AsyncMock(
            return_value=[
                {
                    "type": "merge",
                    "skill_names": ["a", "b"],
                    "reason": "重叠",
                }
            ]
        )
        monkeypatch.setattr(cons_mod, "get_consolidation_service", lambda: fake_service)
        monkeypatch.setattr(
            cons_mod, "collect_active_skills", lambda: [{"name": "a"}, {"name": "b"}]
        )

        task = SkillConsolidationTask(db=tmp_db)
        result = await task.run_async()
        assert result == 1

        audit = SkillAuditLog(db=tmp_db)
        entries = audit.list_entries()
        assert entries[0]["action"] == "consolidation_note"
        assert entries[0]["source"] == "consolidation_cron"

    @pytest.mark.asyncio()
    async def test_no_provider_is_noop(self, tmp_db, monkeypatch):
        """LLM 未装配 → no-op 返回 0，不报错"""
        import backend.skills.consolidator as cons_mod

        monkeypatch.setattr(cons_mod, "get_consolidation_service", lambda: None)
        task = SkillConsolidationTask(db=tmp_db)
        assert await task.run_async() == 0

    @pytest.mark.asyncio()
    async def test_pinned_passed_to_scan(self, tmp_db, monkeypatch):
        """pinned 名单透传给 scan（archive 建议剔除用）"""
        import backend.skills.consolidator as cons_mod

        fake_service = SimpleNamespace()
        fake_service.scan = AsyncMock(return_value=[])
        monkeypatch.setattr(cons_mod, "get_consolidation_service", lambda: fake_service)
        monkeypatch.setattr(cons_mod, "collect_active_skills", lambda: [{"name": "a"}])

        class FakeLifecycle:
            def get_pinned_names(self):
                return {"a"}

        import backend.skills.lifecycle as lifecycle_mod

        monkeypatch.setattr(
            lifecycle_mod, "get_lifecycle_store", lambda: FakeLifecycle()
        )
        task = SkillConsolidationTask(db=tmp_db)
        await task.run_async()
        _, kwargs = fake_service.scan.call_args
        assert kwargs.get("pinned_names") == ["a"]


class TestScheduleRegistration:
    def test_default_schedule_contains_task(self):
        from backend.services._evolution_register import _DEFAULT_SCHEDULE

        # 每周六 05:30 —— 与 plan 文档一致
        assert _DEFAULT_SCHEDULE["skill_consolidation"] == ("30", "5", "6")

    def test_factory_creates_task(self):
        from backend.scheduler.evolution import create_evolution_tasks

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db = Database(f.name)
            db.init_db()
        try:
            tasks = create_evolution_tasks({"skill_consolidation": {"enabled": True}})
            assert isinstance(tasks.get("skill_consolidation"), SkillConsolidationTask)
        finally:
            db.close()


class TestProvenanceInjection:
    def test_consolidation_roundtrip_service_reuse(self):
        """ConsolidationService 从 ReviewService 复用 provider（Round 5 既有契约）"""
        review = ReviewService(_provider("[]"))
        svc = ConsolidationService.from_review_service(review)
        assert svc is not None
        assert svc.llm_provider is review.llm_provider
