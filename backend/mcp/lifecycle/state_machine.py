"""MCP 服务状态机。

定义 MCP 服务的生命周期状态和转换规则。

状态流转：
    CREATED → INITIALIZING → READY → RUNNING ⇄ PAUSED
                                      ↓
                                  SHUTDOWN
"""

from enum import Enum


class MCPState(str, Enum):
    """MCP 服务状态枚举。"""

    CREATED = "created"
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    SHUTDOWN = "shutdown"

    @classmethod
    def initial(cls) -> "MCPState":
        """返回初始状态。"""
        return cls.CREATED


# 合法的状态转换
VALID_TRANSITIONS: dict[MCPState, set[MCPState]] = {
    MCPState.CREATED: {MCPState.INITIALIZING},
    MCPState.INITIALIZING: {MCPState.READY, MCPState.SHUTDOWN},
    MCPState.READY: {MCPState.RUNNING, MCPState.SHUTDOWN},
    MCPState.RUNNING: {MCPState.PAUSED, MCPState.SHUTDOWN},
    MCPState.PAUSED: {MCPState.RUNNING, MCPState.SHUTDOWN},
    MCPState.SHUTDOWN: set(),  # 终态
}


class StateTransitionError(Exception):
    """非法状态转换异常。"""

    def __init__(self, from_state: MCPState, to_state: MCPState):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"非法状态转换: {from_state.value} → {to_state.value}")


class MCPStateMachine:
    """MCP 状态机。"""

    def __init__(self):
        self._state = MCPState.initial()
        self._history: list[MCPState] = [self._state]

    @property
    def state(self) -> MCPState:
        """当前状态。"""
        return self._state

    @property
    def history(self) -> list[MCPState]:
        """状态历史。"""
        return self._history.copy()

    def can_transition_to(self, target: MCPState) -> bool:
        """检查是否可以转换到目标状态。"""
        return target in VALID_TRANSITIONS.get(self._state, set())

    def transition_to(self, target: MCPState) -> None:
        """转换到目标状态。

        Args:
            target: 目标状态

        Raises:
            StateTransitionError: 非法状态转换
        """
        if not self.can_transition_to(target):
            raise StateTransitionError(self._state, target)

        self._state = target
        self._history.append(target)

    def reset(self) -> None:
        """重置状态机到初始状态。"""
        self._state = MCPState.initial()
        self._history = [self._state]
