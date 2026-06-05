"""
工具系统基类
定义工具的基础接口和数据结构
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSchema:
    """工具 Schema - 定义工具的元数据"""
    name: str  # 工具名称
    description: str  # 工具描述
    parameters: dict[str, Any] = field(default_factory=dict)  # JSON Schema 格式参数


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool  # 是否成功
    content: Any = None  # 返回内容
    error: str | None = None  # 错误信息

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        result = {"success": self.success}
        if self.content is not None:
            result["content"] = self.content
        if self.error is not None:
            result["error"] = self.error
        return result


class BaseTool(ABC):
    """
    工具基类

    所有工具必须继承此类并实现:
    - _build_schema(): 返回工具的 Schema
    - execute(): 执行工具逻辑
    """

    def __init__(self):
        self._schema: ToolSchema | None = None

    @property
    def schema(self) -> ToolSchema:
        """获取工具 Schema"""
        if self._schema is None:
            self._schema = self._build_schema()
        return self._schema

    @property
    def name(self) -> str:
        """获取工具名称"""
        return self.schema.name

    @property
    def description(self) -> str:
        """获取工具描述"""
        return self.schema.description

    @abstractmethod
    def _build_schema(self) -> ToolSchema:
        """
        构建工具 Schema

        Returns:
            ToolSchema 对象
        """
        pass

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """
        执行工具

        Args:
            **kwargs: 工具参数

        Returns:
            ToolResult 对象
        """
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name='{self.name}'>"
