"""Phase 3 hook 反馈注入集成测试。

真实 post_tool_use 钩子 + 真实 agent.run_loop:
钩子输出 ``additional_context`` → 以 ``system`` 角色追加到对话历史,
下一轮 LLM 可见。
"""

from __future__ import annotations

import sys
from typing import List, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.data.settings_repo import SettingsRepository

pytestmark = pytest.mark.integration

PY = sys.executable


def _install_hooks(hooks: List[dict]) -> None:
    SettingsRepository().set_json("hooks", hooks)


def _write_hook(tmp_path, body: str) -> str:
    script = tmp_path / "hook.py"
    script.write_text(body, encoding="utf-8")
    return f"{PY} {script}"


def _make_agent(tool_call_name: str, tool_call_args: str, final_text: str) -> SageAgent:
    """构造一个 LLM 在两轮后终止的 agent: 第 1 轮调 tool, 第 2 轮 DONE。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            LLMResponse(
                content="",
                tool_calls=[LLMToolCall(id="call_1", name=tool_call_name, arguments=tool_call_args)],
            ),
            LLMResponse(content=final_text, tool_calls=[]),
        ]
    )
    return agent


async def _collect(agent: SageAgent) -> Tuple[List[AgentEvent], List[dict]]:
    messages: List[dict] = [{"role": "user", "content": "hi"}]
    events = [evt async for evt in agent.run_loop(messages)]
    return events, messages


@pytest.mark.asyncio()
async def test_post_hook_feedback_injected_as_system_message(tmp_path):
    """post_tool_use 钩子的 additional_context → 对话历史增加 system 消息。"""
    cmd = _write_hook(
        tmp_path,
        "import json, sys\n"
        "payload = json.load(sys.stdin)\n"
        "feedback = f\"lint: unused import in {payload['tool_name']}\"\n"
        "print(json.dumps({'decision': 'allow', 'additional_context': feedback, 'severity': 'warning'}))\n",
    )
    _install_hooks([{"event": "post_tool_use", "matcher": "bash", "command": cmd}])

    agent = _make_agent("bash", '{"command": "echo hi"}', "处理完毕")
    events, messages = await _collect(agent)

    step_done = getattr(AgentState, "STEP_DONE", None)
    assert any(e.state == AgentState.DONE for e in events) or (
        step_done is not None and any(e.state == step_done for e in events)
    ), "agent loop should reach done"

    system_msgs = [m for m in messages if m.get("role") == "system" and "钩子反馈" in m.get("content", "")]
    assert len(system_msgs) >= 1, f"expected system feedback message; got {messages}"
    assert "lint: unused import in bash" in system_msgs[-1]["content"]
    assert "警告" in system_msgs[-1]["content"]  # severity=warning → "警告"


@pytest.mark.asyncio()
async def test_post_hook_no_feedback_does_not_inject_system_message(tmp_path):
    """钩子不输出 additional_context → 不注入 system 消息 (零噪声)。"""
    cmd = _write_hook(
        tmp_path,
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'decision': 'allow'}))\n",
    )
    _install_hooks([{"event": "post_tool_use", "matcher": "bash", "command": cmd}])

    agent = _make_agent("bash", '{"command": "echo hi"}', "ok")
    _, messages = await _collect(agent)

    hook_feedback = [
        m for m in messages if m.get("role") == "system" and "钩子反馈" in m.get("content", "")
    ]
    assert len(hook_feedback) == 0


@pytest.mark.asyncio()
async def test_post_hook_multiple_feedbacks_merged(tmp_path):
    """两个 post_tool_use 钩子都输出反馈 → 合并为单条 system 消息。"""
    dir1 = tmp_path / "h1"
    dir1.mkdir()
    dir2 = tmp_path / "h2"
    dir2.mkdir()
    cmd1 = _write_hook(
        dir1,
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'decision': 'allow', 'additional_context': 'line 1: F401'}))\n",
    )
    cmd2 = _write_hook(
        dir2,
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'decision': 'allow', 'additional_context': 'line 5: typo'}))\n",
    )
    _install_hooks([
        {"event": "post_tool_use", "matcher": "bash", "command": cmd1},
        {"event": "post_tool_use", "matcher": "bash", "command": cmd2},
    ])

    agent = _make_agent("bash", '{"command": "echo"}', "done")
    _, messages = await _collect(agent)

    hook_feedback = [
        m for m in messages if m.get("role") == "system" and "钩子反馈" in m.get("content", "")
    ]
    assert len(hook_feedback) == 1, "multiple feedbacks should be merged into one system message"
    content = hook_feedback[0]["content"]
    assert "line 1: F401" in content
    assert "line 5: typo" in content
