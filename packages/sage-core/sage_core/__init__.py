"""Sage 核心领域模型。

零外部依赖的纯 Python 实现，包含：
- 领域实体（entities）
- 值对象（value_objects）
- 仓库接口（repositories）
- 领域服务（services）
- 领域事件（events）
- 异常（exceptions）
"""

__version__ = "0.1.0"

# 导出核心实体
from sage_core.entities.agent import AgentDecision, AgentState
from sage_core.entities.compute import (
    ComputeError,
    ComputeErrorType,
    ComputeRequest,
    ComputeResult,
    ComputeSpec,
)
from sage_core.entities.message import Message, Role, ToolCall
from sage_core.entities.skill import SkillResult, SkillSpec
from sage_core.entities.tool import ToolResult, ToolSpec

# 导出核心异常
from sage_core.exceptions import (
    AgentError,
    LLMError,
    LLMErrorType,
    MaxIterationsError,
    SageBaseError,
    SageMemoryError,
    SecurityError,
    SessionNotFoundError,
    ToolCallError,
    ValidationError,
)

__all__ = [
    # Agent
    "AgentDecision",
    "AgentState",
    # Message
    "Message",
    "Role",
    "ToolCall",
    # Skill
    "SkillResult",
    "SkillSpec",
    # Tool
    "ToolResult",
    "ToolSpec",
    # Compute
    "ComputeError",
    "ComputeErrorType",
    "ComputeRequest",
    "ComputeResult",
    "ComputeSpec",
    # Exceptions
    "AgentError",
    "LLMError",
    "LLMErrorType",
    "MaxIterationsError",
    "SageBaseError",
    "SageMemoryError",
    "SecurityError",
    "SessionNotFoundError",
    "ToolCallError",
    "ValidationError",
]
