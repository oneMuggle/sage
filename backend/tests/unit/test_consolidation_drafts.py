"""巡检建议 → 草稿自动生成测试（Round 9）"""

from __future__ import annotations

import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.data.database import Database
from backend.skills.consolidator import ConsolidationService
from backend.skills.draft_store import SkillDraftStore

pytestmark = pytest.mark.unit


MERGE_JSON = (
    '{"name": "deploy-all", "description": "合并后的部署技能", '
    '"when_to_use": "当用户明确要求把应用程序部署或者发布到指定的目标运行环境时使用该技能", '
    '"content": "# 部署\\n## 步骤\\n1. 构建\\n## 触发条件\\n部署请求\\n## 示例\\n部署"}'
)


def _provider(text: str):
    provider = SimpleNamespace()
    provider.complete = AsyncMock(return_value=SimpleNamespace(text=text))
    return provider


@pytest.fixture()
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
        yield db
        db.close()


@pytest.fixture()
def draft_store(tmp_db):
    return SkillDraftStore(db_path=tmp_db.db_path)


class TestDraftFromSuggestion:
    @pytest.mark.asyncio()
    async def test_merge_generates_draft_fields(self):
        svc = ConsolidationService(_provider(MERGE_JSON))
        suggestion = {"type": "merge", "skill_names": ["deploy", "release"]}
        docs = {"deploy": "# deploy", "release": "# release"}
        fields = await svc.draft_from_suggestion(suggestion, docs)
        assert fields is not None
        assert fields["name"] == "deploy-all"

    @pytest.mark.asyncio()
    async def test_revise_generates_draft_fields(self):
        svc = ConsolidationService(_provider(MERGE_JSON))
        suggestion = {"type": "revise", "skill_names": ["deploy"]}
        docs = {"deploy": "# deploy v1"}
        fields = await svc.draft_from_suggestion(suggestion, docs)
        assert fields is not None

    @pytest.mark.asyncio()
    async def test_archive_returns_none(self):
        svc = ConsolidationService(_provider(MERGE_JSON))
        assert (
            await svc.draft_from_suggestion(
                {"type": "archive", "skill_names": ["old"]}, {"old": "# old"}
            )
            is None
        )

    @pytest.mark.asyncio()
    async def test_llm_failure_returns_none(self):
        provider = SimpleNamespace()
        provider.complete = AsyncMock(side_effect=RuntimeError("down"))
        svc = ConsolidationService(provider)
        assert (
            await svc.draft_from_suggestion(
                {"type": "merge", "skill_names": ["a"]}, {"a": "# a"}
            )
            is None
        )

    @pytest.mark.asyncio()
    async def test_schema_violation_returns_none(self, tmp_db):
        """LLM 输出缺字段/超长描述 → 校验失败返回 None"""
        bad = '{"name": "x"}'
        svc = ConsolidationService(_provider(bad))
        assert (
            await svc.draft_from_suggestion(
                {"type": "merge", "skill_names": ["a"]}, {"a": "# a"}
            )
            is None
        )


class TestGenerateDrafts:
    @pytest.mark.asyncio()
    async def test_drafts_inserted_pending(self, draft_store):
        svc = ConsolidationService(_provider(MERGE_JSON))
        suggestions = [
            {"type": "merge", "skill_names": ["deploy", "release"], "reason": "重叠"},
            {"type": "archive", "skill_names": ["old"], "reason": "过时"},
        ]
        docs = {"deploy": "# d", "release": "# r", "old": "# o"}
        created = await svc.generate_drafts(suggestions, docs, draft_store)
        assert created == 1  # archive 不产草稿
        pending = draft_store.list(status="pending")
        assert len(pending) == 1
        assert pending[0].name == "deploy-all"
        assert pending[0].source_context.get("consolidation") is True

    @pytest.mark.asyncio()
    async def test_single_failure_does_not_break_batch(self, draft_store):
        """第一条草稿生成失败 → 第二条照常入库"""
        calls = {"n": 0}

        async def flaky_draft(suggestion, docs):
            calls["n"] += 1
            if calls["n"] == 1:
                return None  # 第一条失败
            return {
                "name": "rev-1",
                "description": "修订",
                "when_to_use": "当用户明确要求使用修订技能的完整流程时使用该技能",
                "content": "# rev",
            }

        svc = ConsolidationService(_provider("{}"))
        svc.draft_from_suggestion = flaky_draft  # type: ignore[method-assign]
        suggestions = [
            {"type": "merge", "skill_names": ["a"]},
            {"type": "revise", "skill_names": ["b"]},
        ]
        created = await svc.generate_drafts(
            suggestions, {"a": "# a", "b": "# b"}, draft_store
        )
        assert created == 1


class TestReviewServiceImportContract:
    def test_consolidator_uses_review_service_validation(self):
        """草稿校验复用 ReviewService 的 schema/name 校验（单一事实来源）"""
        import inspect

        src = inspect.getsource(ConsolidationService.draft_from_suggestion)
        assert "ReviewService._validate_skill_name" in src
        assert "ReviewService._validate_skill_schema" in src
