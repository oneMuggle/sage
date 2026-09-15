"""审阅触发升级测试（Round 2: LLM 初筛 + 低阈值入队）"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.skills.review_queue import ReviewQueue
from backend.skills.review_service import ReviewService

pytestmark = pytest.mark.unit


def _fake_provider(text: str):
    provider = SimpleNamespace()
    provider.complete = AsyncMock(return_value=SimpleNamespace(text=text))
    return provider


def _fake_provider_ok():
    """generate_draft 期望的合法技能草稿 JSON（满足 schema 校验）"""
    return _fake_provider(
        '{"name": "deploy-flow", "description": "部署流程", '
        '"when_to_use": "当用户明确要求把应用程序部署或者发布到指定的目标运行环境时使用该技能", '
        '"content": "# 部署流程\\n## 步骤\\n1. 构建\\n## 触发条件\\n部署请求\\n## 示例\\n部署到测试环境", '
        '"requires": []}'
    )


class TestShouldGenerate:
    @pytest.mark.asyncio()
    async def test_yes_with_reason(self):
        svc = ReviewService(_fake_provider('{"save_skill": true, "reason": "可复用"}'))
        keep, reason = await svc.should_generate({"tool_calls": []})
        assert keep is True
        assert "可复用" in reason

    @pytest.mark.asyncio()
    async def test_no(self):
        svc = ReviewService(_fake_provider('{"save_skill": false, "reason": "一次性"}'))
        keep, reason = await svc.should_generate({})
        assert keep is False

    @pytest.mark.asyncio()
    async def test_fenced_json_tolerated(self):
        svc = ReviewService(
            _fake_provider('结果如下：\n```json\n{"save_skill": true, "reason": "流程清晰"}\n```')
        )
        keep, _ = await svc.should_generate({})
        assert keep is True

    @pytest.mark.asyncio()
    async def test_garbage_output_is_false(self):
        svc = ReviewService(_fake_provider("不是 JSON"))
        keep, _ = await svc.should_generate({})
        assert keep is False

    @pytest.mark.asyncio()
    async def test_empty_text_is_false(self):
        svc = ReviewService(_fake_provider(""))
        keep, _ = await svc.should_generate({})
        assert keep is False


class TestProcessEventScreening:
    def _make_queue(self, tmp_path, provider, should_generate=None):
        queue = ReviewQueue(db_path=str(tmp_path / "review.db"))
        svc = ReviewService(provider)
        if should_generate is not None:
            svc.should_generate = AsyncMock(return_value=should_generate)
        queue.set_review_service(svc)

        store = SimpleNamespace()
        store.insert = lambda draft: drafts.append(draft)
        drafts: list = []
        queue.set_draft_store(store)
        return queue, drafts

    def _process(self, queue, context, trigger_type="complex_turn"):
        event = SimpleNamespace(
            id=1,
            trigger_type=trigger_type,
            session_id="s1",
            context=context,
            status="pending",
            created_at=0,
        )
        queue._process_event(event)

    def test_screening_false_skips_draft(self, tmp_path):
        """初筛否 → 不起稿"""
        queue, drafts = self._make_queue(
            tmp_path, _fake_provider_ok(), should_generate=(False, "一次性任务")
        )
        self._process(queue, {"tool_calls": [], "needs_screening": True})
        assert drafts == []

    def test_screening_true_generates_draft(self, tmp_path):
        """初筛通过 → 起稿"""
        queue, drafts = self._make_queue(
            tmp_path, _fake_provider_ok(), should_generate=(True, "可复用")
        )
        self._process(queue, {"tool_calls": [], "needs_screening": True})
        assert len(drafts) == 1
        assert drafts[0].name == "deploy-flow"

    def test_no_screening_flag_generates_directly(self, tmp_path):
        """无 needs_screening（复杂回合）→ 不初筛直接起稿"""
        provider = _fake_provider_ok()
        queue, drafts = self._make_queue(tmp_path, provider)
        self._process(queue, {"tool_calls": []})
        assert len(drafts) == 1
        provider.complete.assert_awaited_once()

    def test_explicit_learn_bypasses_screening(self, tmp_path):
        """显式学习触发即使带 needs_screening 也不初筛"""
        queue, drafts = self._make_queue(
            tmp_path, _fake_provider_ok(), should_generate=(False, "不应被问")
        )
        self._process(
            queue,
            {"needs_screening": True, "messages": [{"role": "user", "content": "学一下"}]},
            trigger_type="explicit_learn",
        )
        assert len(drafts) == 1

    def test_screening_exception_marks_failure(self, tmp_path):
        """初筛抛异常 → 事件按失败处理（异常上抛给 worker 循环）"""
        queue, drafts = self._make_queue(tmp_path, _fake_provider_ok())
        queue.review_service.should_generate = AsyncMock(
            side_effect=RuntimeError("provider down")
        )
        with pytest.raises(RuntimeError):
            self._process(queue, {"needs_screening": True})
        assert drafts == []


class TestChatServiceThresholds:
    def test_enqueue_threshold_constants(self):
        from backend.application.services.chat_service import (
            REVIEW_ENQUEUE_TOOL_CALL_THRESHOLD,
            SKILL_NUDGE_TOOL_CALL_THRESHOLD,
        )

        # 入队阈值低于 nudge 阈值 —— 中间地带交给 LLM 初筛
        assert REVIEW_ENQUEUE_TOOL_CALL_THRESHOLD == 2
        assert SKILL_NUDGE_TOOL_CALL_THRESHOLD == 4
