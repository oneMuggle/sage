"""
M6 Hooks 集成测试

真实 subprocess 钩子 + 真实 SageAgent.run_loop 状态机:
1. pre-hook deny terminal 系工具 → 错误 ToolResult + 循环继续至 DONE
2. pre-hook modify → schema 再校验通过后替换参数执行
"""

from __future__ import annotations

import json
import sys
from typing import List, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.data.settings_repo import SettingsRepository

pytestmark = pytest.mark.integration


def _write_hook(tmp_path, body: str) -> str:
    """把钩子脚本写入 tmp_path, 返回 'python script' 形式的命令。"""
    script = tmp_path / "hook.py"
    script.write_text(body, encoding="utf-8")
    return f"{sys.executable} {script}"


def _install_hooks(hooks: List[dict]) -> None:
    SettingsRepository().set_json("hooks", hooks)


def _make_agent(tool_call_name: str, tool_call_args: str, final_text: str) -> SageAgent:
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
async def test_pre_hook_deny_blocks_tool_and_loop_continues(tmp_path):
    """deny 钩子 → 工具不执行、错误结果进消息、循环继续到 DONE。"""
    cmd = _write_hook(
        tmp_path,
        "import json, sys\n"
        "payload = json.load(sys.stdin)\n"
        "print(json.dumps({'decision': 'deny', 'reason': 'blocked:' + payload['tool_name']}))\n",
    )
    _install_hooks([{"event": "pre_tool_use", "matcher": "bash", "command": cmd}])

    agent = _make_agent("bash", '{"command": "rm -rf /"}', "已处理")

    # 钩子 deny 后工具绝不能被执行
    bash_tool = agent.tool_registry.get("bash")
    assert bash_tool is not None

    def _boom(**kwargs):
        raise AssertionError("denied tool must not execute")

    bash_tool.execute = _boom

    events, messages = await _collect(agent)

    states = [e.state for e in events]
    assert AgentState.DONE in states, "loop must continue after deny"
    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is True
    assert "hook 拒绝" in observing.tool_result.content
    assert "blocked:bash" in observing.tool_result.content
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert "hook 拒绝" in tool_msgs[0]["content"]


@pytest.mark.asyncio()
async def test_pre_hook_modify_replaces_args_after_schema_revalidation(tmp_path):
    """modify 钩子 → 参数被替换 (1+1 → 2+2), 工具执行替换后的参数。"""
    cmd = _write_hook(
        tmp_path,
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'decision': 'modify', 'updated_input': {'expression': '2+2'}}))\n",
    )
    _install_hooks([{"event": "pre_tool_use", "matcher": "calc*", "command": cmd}])

    agent = _make_agent("calculator", '{"expression": "1+1"}', "完成")
    events, _messages = await _collect(agent)

    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is False
    content = json.loads(observing.tool_result.content)
    assert content["expression"] == "2+2"
    assert content["result"] == 4


@pytest.mark.asyncio()
async def test_pre_hook_modify_failing_revalidation_keeps_original_args(tmp_path):
    """modify 出的参数缺 required → 忽略修改, 仍用原参数执行。"""
    cmd = _write_hook(
        tmp_path,
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'decision': 'modify', 'updated_input': {'bogus': 1}}))\n",
    )
    _install_hooks([{"event": "pre_tool_use", "matcher": "*", "command": cmd}])

    agent = _make_agent("calculator", '{"expression": "3*3"}', "完成")
    events, _messages = await _collect(agent)

    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is False
    content = json.loads(observing.tool_result.content)
    assert content["expression"] == "3*3"
    assert content["result"] == 9


@pytest.mark.asyncio()
async def test_failing_hook_is_fail_open(tmp_path):
    """非零退出的钩子 → no-op, 工具照常执行。"""
    _install_hooks([{"event": "pre_tool_use", "matcher": "*", "command": "exit 2"}])

    agent = _make_agent("calculator", '{"expression": "5+5"}', "完成")
    events, _messages = await _collect(agent)

    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is False
    content = json.loads(observing.tool_result.content)
    assert content["result"] == 10
    assert any(e.state == AgentState.DONE for e in events)


@pytest.mark.asyncio()
async def test_post_hook_observes_result(tmp_path):
    """post_tool_use 钩子收到工具输出 (写到文件验证 payload)。"""
    marker = tmp_path / "post_seen.txt"
    cmd = _write_hook(
        tmp_path,
        "import json, sys, pathlib\n"
        "payload = json.load(sys.stdin)\n"
        f"pathlib.Path({str(marker)!r}).write_text(\n"
        "    json.dumps({'output': payload.get('tool_output'),\n"
        "                'is_error': payload.get('tool_result_is_error'),\n"
        "                'event': payload.get('hook_event_name')}, ensure_ascii=False)\n"
        ")\n",
    )
    _install_hooks([{"event": "post_tool_use", "matcher": "calc*", "command": cmd}])

    agent = _make_agent("calculator", '{"expression": "7+1"}', "完成")
    events, _messages = await _collect(agent)

    assert any(e.state == AgentState.DONE for e in events)
    seen = json.loads(marker.read_text(encoding="utf-8"))
    assert json.loads(seen["output"])["result"] == 8
    assert seen["is_error"] is False
    assert seen["event"] == "post_tool_use"
