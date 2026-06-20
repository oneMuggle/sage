"""MCP 状态机单元测试。"""

import pytest

from backend.mcp.lifecycle import MCPState, MCPStateMachine, StateTransitionError


class TestMCPStateMachine:
    """测试 MCP 状态机。"""

    def test_initial_state_is_created(self):
        """测试初始状态是 CREATED。"""
        machine = MCPStateMachine()
        assert machine.state == MCPState.CREATED

    def test_valid_transition_created_to_initializing(self):
        """测试合法转换：CREATED → INITIALIZING。"""
        machine = MCPStateMachine()
        assert machine.can_transition_to(MCPState.INITIALIZING)
        machine.transition_to(MCPState.INITIALIZING)
        assert machine.state == MCPState.INITIALIZING

    def test_valid_transition_initializing_to_ready(self):
        """测试合法转换：INITIALIZING → READY。"""
        machine = MCPStateMachine()
        machine.transition_to(MCPState.INITIALIZING)
        machine.transition_to(MCPState.READY)
        assert machine.state == MCPState.READY

    def test_valid_transition_ready_to_running(self):
        """测试合法转换：READY → RUNNING。"""
        machine = MCPStateMachine()
        machine.transition_to(MCPState.INITIALIZING)
        machine.transition_to(MCPState.READY)
        machine.transition_to(MCPState.RUNNING)
        assert machine.state == MCPState.RUNNING

    def test_valid_transition_running_to_paused(self):
        """测试合法转换：RUNNING → PAUSED。"""
        machine = MCPStateMachine()
        machine.transition_to(MCPState.INITIALIZING)
        machine.transition_to(MCPState.READY)
        machine.transition_to(MCPState.RUNNING)
        machine.transition_to(MCPState.PAUSED)
        assert machine.state == MCPState.PAUSED

    def test_valid_transition_paused_to_running(self):
        """测试合法转换：PAUSED → RUNNING。"""
        machine = MCPStateMachine()
        machine.transition_to(MCPState.INITIALIZING)
        machine.transition_to(MCPState.READY)
        machine.transition_to(MCPState.RUNNING)
        machine.transition_to(MCPState.PAUSED)
        machine.transition_to(MCPState.RUNNING)
        assert machine.state == MCPState.RUNNING

    def test_invalid_transition_created_to_running(self):
        """测试非法转换：CREATED → RUNNING。"""
        machine = MCPStateMachine()
        assert not machine.can_transition_to(MCPState.RUNNING)
        with pytest.raises(StateTransitionError):
            machine.transition_to(MCPState.RUNNING)

    def test_invalid_transition_running_to_ready(self):
        """测试非法转换：RUNNING → READY。"""
        machine = MCPStateMachine()
        machine.transition_to(MCPState.INITIALIZING)
        machine.transition_to(MCPState.READY)
        machine.transition_to(MCPState.RUNNING)
        assert not machine.can_transition_to(MCPState.READY)
        with pytest.raises(StateTransitionError):
            machine.transition_to(MCPState.READY)

    def test_shutdown_is_terminal_state(self):
        """测试 SHUTDOWN 是终态。"""
        machine = MCPStateMachine()
        machine.transition_to(MCPState.INITIALIZING)
        machine.transition_to(MCPState.SHUTDOWN)
        assert machine.state == MCPState.SHUTDOWN
        assert not machine.can_transition_to(MCPState.READY)
        assert not machine.can_transition_to(MCPState.RUNNING)

    def test_history_tracks_all_transitions(self):
        """测试历史记录所有转换。"""
        machine = MCPStateMachine()
        machine.transition_to(MCPState.INITIALIZING)
        machine.transition_to(MCPState.READY)
        machine.transition_to(MCPState.RUNNING)

        expected = [
            MCPState.CREATED,
            MCPState.INITIALIZING,
            MCPState.READY,
            MCPState.RUNNING,
        ]
        assert machine.history == expected

    def test_reset_returns_to_initial_state(self):
        """测试重置返回初始状态。"""
        machine = MCPStateMachine()
        machine.transition_to(MCPState.INITIALIZING)
        machine.transition_to(MCPState.READY)
        machine.reset()
        assert machine.state == MCPState.CREATED
        assert machine.history == [MCPState.CREATED]
