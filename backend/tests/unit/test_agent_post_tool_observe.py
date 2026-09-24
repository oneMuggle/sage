# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""post-execute 段测试（DSH 对标 R7，GT3）。

覆盖 `_post_tool_observe`：tool 消息落历史（capped）、post_tool_use
反馈按 severity 注入、error 钩子在失败时触发、成功时不触发。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.legacy.agent import SageAgent

pytestmark = pytest.mark.unit


def _tc(name="read_file"):
    tc = MagicMock()
    tc.id = f"call_{name}"
    tc.name = name
    return tc


def _hook_outcome(has_feedback=False, severity="info", context=""):
    o = MagicMock()
    o.has_feedback = has_feedback
    o.severity = severity
    o.additional_context = context
    return o


def _run_observe(agent, tc, args, hooks, messages, content, is_error):
    import asyncio

    return asyncio.get_event_loop().run_until_complete(
        agent._post_tool_observe(
            tc, args, hooks, messages, content, is_error, cap_fn=lambda c: c
        )
    )


class TestPostToolObserve:
    def test_appends_capped_tool_message(self):
        agent = SageAgent()
        messages = []
        with patch(
            "backend.core.legacy.agent.run_event_hooks",
            new=AsyncMock(return_value=_hook_outcome()),
        ):
            _run_observe(agent, _tc(), {"p": 1}, [], messages, "结果内容", False)
        assert len(messages) == 1
        assert messages[0]["role"] == "tool"
        assert messages[0]["tool_call_id"] == "call_read_file"
        assert messages[0]["content"] == "结果内容"

    def test_post_hook_feedback_injected_with_severity(self):
        agent = SageAgent()
        messages = []
        hooks = [MagicMock()]
        with patch(
            "backend.core.legacy.agent.run_event_hooks",
            new=AsyncMock(
                return_value=_hook_outcome(True, "warning", "注意缩进格式")
            ),
        ) as run_hooks:
            _run_observe(
                agent, _tc(), {"p": 1}, hooks, messages, "结果", False
            )
            assert run_hooks.await_count == 1
            assert run_hooks.await_args.args[1] == "post_tool_use"
        assert len(messages) == 2
        assert messages[1]["role"] == "system"
        assert "[钩子反馈·警告]" in messages[1]["content"]
        assert "注意缩进格式" in messages[1]["content"]

    @pytest.mark.asyncio()
    async def test_error_hook_receives_is_error_flag(self):
        """error 钩子总是被调用、is_error 原样透传（内部自行过滤）。"""
        agent = SageAgent()
        agent._maybe_fire_error_hook = AsyncMock()
        with patch(
            "backend.core.legacy.agent.run_event_hooks",
            new=AsyncMock(return_value=_hook_outcome()),
        ):
            await agent._post_tool_observe(
                _tc(), {}, [], [], "坏了", True, cap_fn=lambda c: c
            )
            agent._maybe_fire_error_hook.assert_awaited_once_with(
                [], "read_file", "坏了", True
            )

            await agent._post_tool_observe(
                _tc(), {}, [], [], "好了", False, cap_fn=lambda c: c
            )
            assert agent._maybe_fire_error_hook.await_count == 2
            agent._maybe_fire_error_hook.assert_awaited_with(
                [], "read_file", "好了", False
            )

    def test_no_feedback_no_extra_message(self):
        agent = SageAgent()
        agent._maybe_fire_error_hook = AsyncMock()
        messages = []
        with patch(
            "backend.core.legacy.agent.run_event_hooks",
            new=AsyncMock(return_value=_hook_outcome(False)),
        ):
            _run_observe(agent, _tc(), {}, [MagicMock()], messages, "ok", False)
        assert len(messages) == 1
