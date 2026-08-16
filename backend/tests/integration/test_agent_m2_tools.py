"""M2 agent 工具面 — run_loop 集成测试。

- grep_search → edit_file 往返：mock LLM 先 grep 定位再 edit 修复，
  真实工具在 tmp_path workspace 上跑，验证文件内容被改且事件流完整。
- repl 在 PROMPT 模式下触发 PERMISSION_REQUEST 审批事件，批准后真实
  子进程执行并回传 stdout。
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.domain.tool_policy import ToolPolicy
from backend.services.permission_gate import init_permission_gate, reset_permission_gate
from backend.tools import register_all_tools
from backend.tools.bash_validation import validate_bash
from backend.tools.permissions import PermissionEnforcer, PermissionMode
from backend.tools.registry import ToolRegistry

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _gate_lifecycle():
    """每个测试独立 gate，防跨测试挂起请求泄漏。"""
    reset_permission_gate()
    yield
    reset_permission_gate()


def _response(tool_calls=None, content: str = "") -> LLMResponse:
    return LLMResponse(content=content, tool_calls=tool_calls or [])


def _agent_with_real_tools(tmp_path) -> SageAgent:
    """SageAgent 挂真实工具注册表（workspace 绑定 tmp_path）。"""
    agent = SageAgent()
    registry = ToolRegistry()
    register_all_tools(registry, policy=ToolPolicy(workspace_root=str(tmp_path)))
    agent.tool_registry = registry
    return agent


@pytest.mark.asyncio()
async def test_run_loop_grep_then_edit_round_trip_in_workspace(tmp_path):
    """grep_search 定位 → edit_file 修复，真实工具往返 + 文件落盘验证。"""
    # Arrange: workspace 内一个含待修标记的文件
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("def hello():\n    return 'TODO_FIXME'\n", encoding="utf-8")

    agent = _agent_with_real_tools(tmp_path)
    agent.permission_enforcer = PermissionEnforcer(
        mode=PermissionMode.WORKSPACE_WRITE, rules=[], bash_validator=validate_bash
    )

    grep_call = LLMToolCall(
        id="c1",
        name="grep_search",
        arguments=json.dumps(
            {"pattern": "TODO_FIXME", "path": str(tmp_path), "output_mode": "content"}
        ),
    )
    edit_call = LLMToolCall(
        id="c2",
        name="edit_file",
        arguments=json.dumps(
            {
                "file_path": str(target),
                "old_string": "return 'TODO_FIXME'",
                "new_string": "return 'hello world'",
            }
        ),
    )
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _response(tool_calls=[grep_call]),
            _response(tool_calls=[edit_call]),
            _response(content="已修复"),
        ]
    )

    # Act
    events = [e async for e in agent.run_loop([{"role": "user", "content": "修掉 TODO"}])]

    # Assert —— 两次工具调用都成功
    observings = [e for e in events if e.state == AgentState.OBSERVING]
    assert len(observings) == 2
    assert all(o.tool_result.is_error is False for o in observings)

    # grep 结果含目标文件的匹配行
    grep_payload = json.loads(observings[0].tool_result.content)
    assert any(str(target) in line for line in grep_payload["matches"])

    # edit 落盘生效
    edit_payload = json.loads(observings[1].tool_result.content)
    assert edit_payload["replacements"] == 1
    assert "hello world" in target.read_text(encoding="utf-8")
    assert "TODO_FIXME" not in target.read_text(encoding="utf-8")

    # READ/WRITE 工具在 workspace_write 下不触发审批
    assert AgentState.PERMISSION_REQUEST not in [e.state for e in events]
    assert events[-1].state == AgentState.DONE


@pytest.mark.asyncio()
async def test_run_loop_edit_outside_workspace_denied_by_boundary(tmp_path):
    """workspace_write 放行 edit_file 能力，但工具内边界检查拒绝越界写入。"""
    # Arrange: workspace 与外部文件分离
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")

    agent = _agent_with_real_tools(workspace)
    agent.permission_enforcer = PermissionEnforcer(
        mode=PermissionMode.WORKSPACE_WRITE, rules=[], bash_validator=validate_bash
    )
    edit_call = LLMToolCall(
        id="c1",
        name="edit_file",
        arguments=json.dumps(
            {"file_path": str(outside), "old_string": "secret", "new_string": "leak"}
        ),
    )
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[_response(tool_calls=[edit_call]), _response(content="done")]
    )

    # Act
    events = [e async for e in agent.run_loop([{"role": "user", "content": "x"}])]

    # Assert —— 权限矩阵放行，但工具边界守卫拦下写入
    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is True
    assert "path_outside_workspace" in observing.tool_result.content
    assert outside.read_text(encoding="utf-8") == "secret\n"
    assert events[-1].state == AgentState.DONE


@pytest.mark.asyncio()
async def test_run_loop_repl_triggers_permission_request_under_prompt_mode():
    """PROMPT 模式: repl（EXECUTE）→ PERMISSION_REQUEST → 批准后真实执行。"""
    # Arrange
    gate = init_permission_gate()
    agent = SageAgent()  # 默认注册表含 repl
    agent.permission_enforcer = PermissionEnforcer(
        mode=PermissionMode.PROMPT, rules=[], bash_validator=validate_bash
    )
    repl_call = LLMToolCall(
        id="r1",
        name="repl",
        arguments=json.dumps({"code": "print('hello from repl')", "timeout": 30}),
    )
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[_response(tool_calls=[repl_call]), _response(content="跑完了")]
    )

    async def approver():
        await asyncio.sleep(0.05)
        pending = gate.pending()
        assert len(pending) == 1
        assert pending[0].tool_name == "repl"
        assert gate.answer(pending[0].request_id, approved=True) is True

    # Act
    approver_task = asyncio.create_task(approver())
    events = [e async for e in agent.run_loop([{"role": "user", "content": "算一下"}])]
    await approver_task

    # Assert —— 审批事件先于执行，批准后真实子进程产出 stdout
    states = [e.state for e in events]
    assert AgentState.PERMISSION_REQUEST in states
    perm_evt = next(e for e in events if e.state == AgentState.PERMISSION_REQUEST)
    assert perm_evt.permission_request["tool_name"] == "repl"
    assert states.index(AgentState.PERMISSION_REQUEST) < states.index(AgentState.OBSERVING)

    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is False
    payload = json.loads(observing.tool_result.content)
    assert payload["exit_code"] == 0
    assert "hello from repl" in payload["stdout"]
    assert events[-1].state == AgentState.DONE
