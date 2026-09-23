# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""审批闸口测试（DSH 对标 R6，GT2）。

覆盖 `_approval_gate` async generator：先流式产出 PERMISSION_REQUEST
事件再 await 应答（顺序契约）、批准/拒绝决议写入 result_box、
answered_by 进入拒绝 reason。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.core.legacy.agent import SageAgent
from backend.tools.permissions import PermissionDecision

pytestmark = pytest.mark.unit


def _tc(name="bash"):
    tc = MagicMock()
    tc.name = name
    return tc


def _needs_approval_decision():
    # 不变量：needs_approval=True 时 allowed 必须为 False（enforcer 的
    # ask 状态：先审批，未批前不放行）
    return PermissionDecision(
        allowed=False, needs_approval=True, reason="风险命令需审批"
    )


def _answer(approved, answered_by="user"):
    a = MagicMock()
    a.approved = approved
    a.answered_by = answered_by
    return a


def _collect_events_and_result(agent, answer):
    """驱动 _approval_gate，返回 (events, final_decision)。"""
    box = {}

    async def _run():
        events = []
        async for ev in agent._approval_gate(
            _tc(), {"cmd": "ls"}, _needs_approval_decision(), 3, box
        ):
            events.append(ev)
        return events, box["decision"]

    with patch.object(agent, "_await_approval_answer", return_value=answer):
        import asyncio

        return asyncio.get_event_loop().run_until_complete(_run())


class TestApprovalGate:
    def test_yields_permission_request_before_await(self):
        agent = SageAgent()
        events, decision = _collect_events_and_result(agent, _answer(True))
        assert len(events) == 1
        ev = events[0]
        assert ev.state.value == "permission_request"
        assert ev.permission_request["tool_name"] == "bash"
        # 批准决议
        assert decision.allowed is True
        assert decision.needs_approval is False
        assert "用户已批准" in decision.reason

    def test_denied_decision_carries_answered_by(self):
        agent = SageAgent()
        events, decision = _collect_events_and_result(
            agent, _answer(False, answered_by="auto-deny")
        )
        assert len(events) == 1
        assert decision.allowed is False
        assert decision.needs_approval is False
        assert "auto-deny" in decision.reason

    def test_original_reason_preserved_in_new_decision(self):
        agent = SageAgent()
        _, decision = _collect_events_and_result(agent, _answer(True))
        assert "风险命令需审批" in decision.reason

    def test_request_event_carries_iteration_and_agent_id(self):
        agent = SageAgent()
        agent.agent_id = "agent-test"
        box = {}

        async def _run():
            return [ev async for ev in agent._approval_gate(
                _tc(), {}, _needs_approval_decision(), 7, box
            )]

        import asyncio

        with patch.object(
            agent, "_await_approval_answer", return_value=_answer(True)
        ):
            events = asyncio.get_event_loop().run_until_complete(_run())
        assert events[0].iteration == 7
        assert events[0].agent_id == "agent-test"
        assert box["decision"].allowed is True
