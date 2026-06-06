"""消息领域模型（纯，零外部依赖）。

提供 Sage 内部统一的消息表示，区别于 LLM provider 的具体 schema：
- ``Role``     ：消息角色枚举
- ``ToolCall`` ：模型发起的工具调用请求
- ``Message``  ：单条对话消息

注意：domain 层禁止使用 pydantic。如果 api 层需要校验，请在 api/schemas
中单独定义 pydantic 模型并与本模块互转。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    """对话消息角色。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    """模型发起的工具调用请求。

    Attributes:
        name:  工具/函数名
        args:  调用参数（已解析为 dict，不再是 JSON 字符串）
        id:    OpenAI tool call id，可选
    """

    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass
class Message:
    """单条对话消息。

    Attributes:
        role:          消息角色
        content:       文本内容（assistant 在 tool_calls 场景下可能为空字符串）
        tool_calls:    当 role == ASSISTANT 且模型要调用工具时填充
        tool_call_id:  当 role == TOOL 时，对应的工具调用 id
    """

    role: Role
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
