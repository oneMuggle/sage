"""SubagentRunner steering 边界投递（O1）+ 会话归因（O3）单测。

- O1: run 启动前投递 pending steering；THINKING 迭代边界再投递；
  mark_delivered 生命周期迁移；repo 未接线零影响。
- O3: session_id 非空透传 child.run_loop；为空时不传（兼容老签名桩）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import List
from unittest.mock import patch

import pytest

from backend.core.legacy.agent_state import AgentEvent, AgentState

_DUMMY_PROFILE = {"system_prompt": "你是测试子 agent", "tools": []}


def _make_task(goal: str = "调研 X"):
    from backend.orchestration.models import Task

    return Task(
        task_id="task-t1", name="T1", description=goal,
        parameters={"goal": goal},
    )


def _ctx(context_id: str, content: str, status: str = "pending"):
    return SimpleNamespace(
        context_id=context_id,
        message_type="clarification",
        content_redacted=content,
        status=status,
    )


class _FakeContextRepo:
    """内存版 OrchestrationContextRepository —— 只实现 runner 用到的两面。"""

    def __init__(self, messages=None):
        self.messages = list(messages or [])
        self.delivered: List[str] = []

    def list_pending(self, task_id, apply_mode=None):
        return [m for m in self.messages if m.status == "pending"]

    def mark_delivered(self, context_id):
        self.delivered.append(context_id)
        for m in self.messages:
            if m.context_id == context_id:
                m.status = "delivered"


class _BoundaryFakeAgent:
    """第二个 THINKING 边界前模拟 steer 端点写入，验证边界投递。"""

    def __init__(self, repo: _FakeContextRepo):
        self.repo = repo
        self.messages_after_second_boundary = None
        self.init_message_count = None

    async def run_loop(self, messages, max_iterations=None, llm_config=None):
        self.init_message_count = len(messages)
        # 边界 1：repo 为空 → 投递 no-op
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        # 模拟运行中 steer 端点写入一条 pending
        self.repo.messages.append(_ctx("ctx-mid", "补充约束：只看 A 股"))
        # 边界 2：runner 处理 THINKING 时完成投递
        yield AgentEvent(state=AgentState.THINKING, iteration=1)
        self.messages_after_second_boundary = [
            m["content"] for m in messages if m["role"] == "user"
        ]
        yield AgentEvent(state=AgentState.DONE, content="ok")


@pytest.mark.asyncio()
async def test_initial_pending_context_injected_before_run():
    """run 启动前已存在的 pending steering → 注入首条 user 消息之后。"""
    from backend.orchestration.subagent_runner import SubagentRunner

    repo = _FakeContextRepo([_ctx("ctx-1", "请重点关注成本口径")])
    captured = {}

    class _CaptureAgent:
        def __init__(self, agent_id=None, policy=None):
            pass

        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            captured["user_contents"] = [
                m["content"] for m in messages if m["role"] == "user"
            ]
            yield AgentEvent(state=AgentState.DONE, content="done")

    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch("backend.orchestration.subagent_runner.SageAgent", _CaptureAgent):
        runner = SubagentRunner(
            context_repo=repo, context_task_id="t1"
        )
        result = await runner(_make_task(), "researcher")

    assert result["status"] == "succeeded"
    # goal 是首条 user 消息，steering 注入其后，带类型前缀
    assert captured["user_contents"][0] == "调研 X"
    assert any("【父代理/用户补充 · clarification】请重点关注成本口径" in c
               for c in captured["user_contents"][1:])
    assert repo.delivered == ["ctx-1"]


@pytest.mark.asyncio()
async def test_pending_context_injected_at_thinking_boundary():
    """THINKING 边界投递 —— 边界后写入的 pending 在下一轮迭代前可见。"""
    from backend.orchestration.subagent_runner import SubagentRunner

    repo = _FakeContextRepo()
    fake = _BoundaryFakeAgent(repo)

    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch("backend.orchestration.subagent_runner.SageAgent", return_value=fake):
        runner = SubagentRunner(context_repo=repo, context_task_id="t1")
        await runner(_make_task(), "researcher")

    assert fake.init_message_count == 2  # system + user(goal)，启动时无 pending
    assert any("【父代理/用户补充 · clarification】补充约束：只看 A 股" in c
               for c in fake.messages_after_second_boundary)
    assert repo.delivered == ["ctx-mid"]


@pytest.mark.asyncio()
async def test_delivered_messages_not_reinjected():
    """已 delivered 的消息不再重复注入。"""
    from backend.orchestration.subagent_runner import SubagentRunner

    repo = _FakeContextRepo([_ctx("ctx-1", "旧消息", status="delivered")])
    captured = {}

    class _CaptureAgent:
        def __init__(self, agent_id=None, policy=None):
            pass

        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            captured["count"] = len(messages)
            yield AgentEvent(state=AgentState.DONE, content="done")

    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch("backend.orchestration.subagent_runner.SageAgent", _CaptureAgent):
        runner = SubagentRunner(context_repo=repo, context_task_id="t1")
        await runner(_make_task(), "researcher")

    assert captured["count"] == 2  # 只剩 system + user(goal)
    assert repo.delivered == []


@pytest.mark.asyncio()
async def test_repo_failure_degrades_silently():
    """repo 拉取/迁移抛错 → 降级继续，子任务正常完成。"""
    from backend.orchestration.subagent_runner import SubagentRunner

    class _BrokenRepo:
        def list_pending(self, task_id, apply_mode=None):
            raise RuntimeError("db down")

        def mark_delivered(self, context_id):
            raise RuntimeError("db down")

    class _OkAgent:
        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            yield AgentEvent(state=AgentState.DONE, content="done")

    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch(
        "backend.orchestration.subagent_runner.SageAgent", return_value=_OkAgent()
    ):
        runner = SubagentRunner(context_repo=_BrokenRepo(), context_task_id="t1")
        result = await runner(_make_task(), "researcher")

    assert result["status"] == "succeeded"


@pytest.mark.asyncio()
async def test_session_id_passed_to_child_run_loop():
    """O3: session_id 非空 → child.run_loop 收到 session_id kwarg。"""
    from backend.orchestration.subagent_runner import SubagentRunner

    captured = {}

    class _SessionCaptureAgent:
        def __init__(self, agent_id=None, policy=None):
            pass

        async def run_loop(self, messages, max_iterations=None,
                           llm_config=None, session_id=None):
            captured["session_id"] = session_id
            yield AgentEvent(state=AgentState.DONE, content="ok")

    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch("backend.orchestration.subagent_runner.SageAgent", _SessionCaptureAgent):
        runner = SubagentRunner(session_id="sess-42")
        result = await runner(_make_task(), "researcher")

    assert result["status"] == "succeeded"
    assert captured["session_id"] == "sess-42"


@pytest.mark.asyncio()
async def test_session_id_omitted_when_unset():
    """O3: session_id 为空 → 不传 kwarg（兼容只接受三参的老签名桩）。"""
    from backend.orchestration.subagent_runner import SubagentRunner

    class _LegacySignatureAgent:
        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            yield AgentEvent(state=AgentState.DONE, content="ok")

    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch(
        "backend.orchestration.subagent_runner.SageAgent",
        return_value=_LegacySignatureAgent(),
    ):
        runner = SubagentRunner()
        result = await runner(_make_task(), "researcher")

    assert result["status"] == "succeeded"
