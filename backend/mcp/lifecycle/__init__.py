"""MCP 生命周期模块。

提供 MCP 服务的生命周期管理，包括：
- 状态机
- 生命周期管理器
- 健康检查
- 资源清理
"""

from .manager import (
    MCPLifecycleManager,
    MCPNotReadyError,
    MCPServiceError,
)
from .state_machine import MCPState, MCPStateMachine, StateTransitionError

__all__ = [
    "MCPState",
    "MCPStateMachine",
    "StateTransitionError",
    "MCPLifecycleManager",
    "MCPServiceError",
    "MCPNotReadyError",
]
