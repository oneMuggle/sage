"""Sage 领域模型层（零外部依赖）。

只允许依赖 Python 标准库（``typing`` / ``dataclasses`` / ``enum`` /
``abc``）。**不得** import fastapi / pydantic / httpx / sqlite3 或
任何 backend 内部模块。

P2 阶段（六边形架构重构）将本层作为业务核心，application 与 adapters
均向内依赖于 domain。
"""

from backend.domain.agent import AgentDecision, AgentState
from backend.domain.errors import LLMError, LLMErrorType
from backend.domain.exceptions import (
    AgentError,
    MaxIterationsError,
    SageBaseError,
    SageMemoryError,
    SecurityError,
    SessionNotFoundError,
    ToolCallError,
    ValidationError,
)
from backend.domain.message import Message, Role, ToolCall
from backend.domain.skill import SkillResult, SkillSpec
from backend.domain.tool import ToolResult, ToolSpec

__all__ = [
    # agent
    "AgentDecision",
    "AgentState",
    # message
    "Message",
    "Role",
    "ToolCall",
    # tool
    "ToolResult",
    "ToolSpec",
    # skill
    "SkillResult",
    "SkillSpec",
    # errors
    "LLMError",
    "LLMErrorType",
    # exceptions
    "AgentError",
    "MaxIterationsError",
    "SageBaseError",
    "SageMemoryError",
    "SecurityError",
    "SessionNotFoundError",
    "ToolCallError",
    "ValidationError",
]
