"""工具领域模型（纯，零外部依赖）。

仅承载工具的规格与执行结果数据，不包含任何执行/IO 逻辑。
真正的 ``BaseTool`` 抽象与实现保留在 ``backend.tools`` 中。
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSpec:
    """工具规格（OpenAI tool / function schema 兼容）。

    Attributes:
        name:        工具名（唯一）
        description: 工具描述（送入 LLM 的自然语言说明）
        parameters:  JSON Schema 格式的参数定义
    """

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """工具执行结果。

    Attributes:
        success:  是否成功
        output:   成功时的输出文本（已序列化为字符串）
        error:    失败时的错误描述
        metadata: 附加元数据（如耗时、token 估算等）
    """

    success: bool
    output: str = ""
    error: str | None = None
    metadata: dict[str, Any] | None = None
