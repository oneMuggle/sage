"""M1 工具安全加固 — SageAgent.run_loop 权限执行集成测试。

验证 enforcement-before-dispatch 接线:
- PROMPT 模式下 EXECUTE 工具触发 permission_request 流事件;
  并发任务 ~50ms 后应答批准 → 工具执行 → DONE。
- 拒绝应答 → 注入 "权限拒绝" 错误 ToolResult, 工具不执行, 循环正常到 DONE。
- 超时未应答 → default-deny, 循环继续。
- gate 未初始化 → default-deny (不挂起)。
- settings 中 permission_mode 被 run_loop 起点读取。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.data.settings_repo import SettingsRepository
from backend.services.permission_gate import (
    get_permission_gate,
    init_permission_gate,
    reset_permission_gate,
)
from backend.tools.bash_validation import validate_bash
from backend.tools.permissions import (
    PermissionEnforcer,
    PermissionMode,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _gate_lifecycle():
    """每个测试独立 gate, 防止跨测试挂起请求泄漏。"""
    # gate 是进程级单例（main.py lifespan shutdown 已负责常见清理），
    # 此处兜底确保本文件内绝对干净。settings 虽因 autouse setup_test_db
    # 的每测试独立 temp DB 本不会跨测试泄漏，但我们改写 permission_mode /
    # permission_rules 后写回原值，保持"写后必还"的卫生。
    _repo = SettingsRepository()
    _prev_mode = _repo.get("permission_mode")
    _prev_rules = _repo.get_json("permission_rules")
    reset_permission_gate()
    yield
    reset_permission_gate()
    if _prev_mode is None:
        _repo.delete("permission_mode")
    else:
        _repo.set("permission_mode", _prev_mode)
    if _prev_rules is None:
        _repo.delete("permission_rules")
    else:
        _repo.set_json("permission_rules", _prev_rules)


def _make_response(content: str = "", tool_calls=None) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=tool_calls or [])


def _terminal_call(call_id: str = "call_term", command: str = "echo hi") -> LLMToolCall:
    return LLMToolCall(
        id=call_id,
        name="terminal",
        arguments='{"command": "%s"}' % command  # noqa: UP031  # JSON 模板保留 % 格式更直观
    )


def _agent_with_stub_tool(tool_calls, final_content: str = "执行完毕") -> tuple:
    """构造 LLM mock (先返回 tool_call 再返回终答) + 存根 EXECUTE 工具。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=tool_calls),
            _make_response(content=final_content),
        ]
    )
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(
        return_value=MagicMock(success=True, content={"stdout": "hi\n"}, error=None)
    )
    agent.tool_registry.get = MagicMock(return_value=mock_tool)
    return agent, mock_tool


@pytest.mark.asyncio()
async def test_run_loop_prompt_mode_yields_permission_request_then_executes_on_approval():
    """PROMPT 模式: terminal 调用 → permission_request 事件 → 批准后执行 → DONE。"""
    # Arrange: settings 走真实路径 (permission_mode=prompt), gate 初始化
    SettingsRepository().set("permission_mode", "prompt")
    gate = init_permission_gate()
    agent, mock_tool = _agent_with_stub_tool([_terminal_call()])

    answered = {}

    async def approver():
        # ~50ms 后应答挂起请求
        await asyncio.sleep(0.05)
        pending = gate.pending()
        assert len(pending) == 1
        answered["request"] = pending[0]
        assert gate.answer(pending[0].request_id, approved=True) is True

    # Act
    approver_task = asyncio.create_task(approver())
    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "跑个命令"}]):
        events.append(evt)
    await approver_task

    # Assert —— 流事件顺序与契约
    states = [e.state for e in events]
    assert AgentState.PERMISSION_REQUEST in states
    perm_evt = next(e for e in events if e.state == AgentState.PERMISSION_REQUEST)
    payload = perm_evt.permission_request
    assert payload is not None
    assert set(payload.keys()) == {
        "request_id",
        "tool_name",
        "args_summary",
        "risk",
        "message",
        "created_at",
    }
    assert payload["tool_name"] == "terminal"
    assert payload["request_id"] == answered["request"].request_id
    # permission_request 在 ACTING 之后, OBSERVING 之前
    assert states.index(AgentState.ACTING) < states.index(AgentState.PERMISSION_REQUEST)
    assert states.index(AgentState.PERMISSION_REQUEST) < states.index(AgentState.OBSERVING)

    # 批准后工具真正执行, 循环走到 DONE
    mock_tool.execute.assert_called_once_with(command="echo hi")
    assert events[-1].state == AgentState.DONE


@pytest.mark.asyncio()
async def test_run_loop_denial_injects_error_tool_result_and_continues_to_done():
    """用户拒绝 → 注入 "权限拒绝" 错误结果, 工具不执行, 循环继续到 DONE。"""
    # Arrange
    gate = init_permission_gate()
    agent, mock_tool = _agent_with_stub_tool([_terminal_call()])
    agent.permission_enforcer = PermissionEnforcer(
        mode=PermissionMode.PROMPT, rules=[], bash_validator=validate_bash
    )

    async def denier():
        await asyncio.sleep(0.05)
        pending = gate.pending()
        assert len(pending) == 1
        gate.answer(pending[0].request_id, approved=False)

    # Act
    denier_task = asyncio.create_task(denier())
    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "跑个命令"}]):
        events.append(evt)
    await denier_task

    # Assert
    mock_tool.execute.assert_not_called()
    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is True
    assert "权限拒绝" in observing.tool_result.content
    assert "未获批准" in observing.tool_result.content
    # 循环优雅继续: LLM 收到错误工具消息后给出终答 → DONE (不是 FAILED)
    assert events[-1].state == AgentState.DONE
    failed = [e for e in events if e.state == AgentState.FAILED]
    assert failed == []


@pytest.mark.asyncio()
async def test_run_loop_approval_timeout_defaults_to_deny_and_loop_continues():
    """无人应答 → 超时 default-deny, 循环不挂死, 继续到 DONE。"""
    # Arrange
    init_permission_gate()
    agent, mock_tool = _agent_with_stub_tool([_terminal_call()])
    agent.permission_enforcer = PermissionEnforcer(
        mode=PermissionMode.PROMPT, rules=[], bash_validator=validate_bash
    )
    agent.approval_timeout = 0.05  # 缩短超时加速测试

    # Act
    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    # Assert
    mock_tool.execute.assert_not_called()
    assert AgentState.PERMISSION_REQUEST in [e.state for e in events]
    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is True
    assert "timeout" in observing.tool_result.content
    assert events[-1].state == AgentState.DONE


@pytest.mark.asyncio()
async def test_run_loop_without_gate_defaults_to_deny_without_hanging():
    """gate 未初始化 (get_permission_gate()=None) → default-deny, 不挂起。"""
    # Arrange
    reset_permission_gate()
    assert get_permission_gate() is None
    agent, mock_tool = _agent_with_stub_tool([_terminal_call()])
    agent.permission_enforcer = PermissionEnforcer(
        mode=PermissionMode.PROMPT, rules=[], bash_validator=validate_bash
    )

    # Act
    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    # Assert
    mock_tool.execute.assert_not_called()
    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is True
    assert "权限拒绝" in observing.tool_result.content
    assert events[-1].state == AgentState.DONE


@pytest.mark.asyncio()
async def test_run_loop_workspace_write_mode_executes_read_tools_without_prompt():
    """workspace_write 默认模式下 READ 工具直接执行, 不产生审批事件。"""
    # Arrange: 默认 settings (无 permission_mode → workspace_write)
    init_permission_gate()
    agent = SageAgent()
    agent.llm_client = MagicMock()
    calc_call = LLMToolCall(id="c1", name="calculator", arguments='{"expression": "1+1"}')
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=[calc_call]),
            _make_response(content="2"),
        ]
    )
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(
        return_value=MagicMock(success=True, content={"result": 2}, error=None)
    )
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    # Act
    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "1+1"}]):
        events.append(evt)

    # Assert
    assert AgentState.PERMISSION_REQUEST not in [e.state for e in events]
    mock_tool.execute.assert_called_once_with(expression="1+1")
    assert events[-1].state == AgentState.DONE


@pytest.mark.asyncio()
async def test_run_loop_deny_rule_from_settings_blocks_tool_before_dispatch():
    """settings 里的 deny 规则在 run 起点装载 → 工具调用被拒且不触发审批。"""
    # Arrange
    repo = SettingsRepository()
    repo.set("permission_mode", "full_access")
    repo.set_json("permission_rules", [{"tool_pattern": "terminal", "decision": "deny"}])
    init_permission_gate()
    agent, mock_tool = _agent_with_stub_tool([_terminal_call()])

    # Act
    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    # Assert
    mock_tool.execute.assert_not_called()
    # deny 规则直接拒, 不走审批通道
    assert AgentState.PERMISSION_REQUEST not in [e.state for e in events]
    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is True
    assert "权限拒绝" in observing.tool_result.content
    assert "deny" in observing.tool_result.content
    assert events[-1].state == AgentState.DONE


@pytest.mark.asyncio()
async def test_run_loop_destructive_command_escalates_even_under_full_access():
    """FULL_ACCESS + rm -rf / → 安全网升级为审批请求 (risk=destructive)。"""
    # Arrange
    gate = init_permission_gate()
    agent, mock_tool = _agent_with_stub_tool(
        [_terminal_call(command="rm -rf /")]
    )
    agent.permission_enforcer = PermissionEnforcer(
        mode=PermissionMode.FULL_ACCESS, rules=[], bash_validator=validate_bash
    )

    async def approver():
        await asyncio.sleep(0.05)
        pending = gate.pending()
        assert len(pending) == 1
        assert pending[0].risk == "destructive"
        gate.answer(pending[0].request_id, approved=False)

    # Act
    task = asyncio.create_task(approver())
    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)
    await task

    # Assert: 即使是 FULL_ACCESS, 破坏性命令也弹了审批且最终被拒
    perm_evt = next(e for e in events if e.state == AgentState.PERMISSION_REQUEST)
    assert perm_evt.permission_request["risk"] == "destructive"
    assert "破坏性" in perm_evt.permission_request["message"]
    mock_tool.execute.assert_not_called()
    assert events[-1].state == AgentState.DONE
