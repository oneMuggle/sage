"""
技能系统基类
定义技能的基础接口和数据结构
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SkillSchema:
    """技能 Schema - 定义技能的元数据"""
    name: str  # 技能名称
    description: str  # 技能描述
    triggers: list[str] = field(default_factory=list)  # 触发关键词列表
    parameters: dict[str, Any] = field(default_factory=dict)  # JSON Schema 格式参数
    examples: list[str] = field(default_factory=list)  # 使用示例


@dataclass
class SkillResult:
    """技能执行结果"""
    content: Any = None  # 返回内容
    metadata: dict[str, Any] = field(default_factory=dict)  # 元数据
    success: bool = True  # 是否成功
    error: str | None = None  # 错误信息

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        result = {
            "success": self.success,
            "content": self.content,
            "metadata": self.metadata
        }
        if self.error:
            result["error"] = self.error
        return result


class BaseSkill(ABC):
    """
    技能基类

    所有技能必须继承此类并实现:
    - _build_schema(): 返回技能的 Schema
    - execute(): 执行技能逻辑
    - match(): 检查文本是否匹配技能触发词
    """

    def __init__(self):
        self._schema: SkillSchema | None = None

    @property
    def schema(self) -> SkillSchema:
        """获取技能 Schema"""
        if self._schema is None:
            self._schema = self._build_schema()
        return self._schema

    @property
    def name(self) -> str:
        """获取技能名称"""
        return self.schema.name

    @property
    def description(self) -> str:
        """获取技能描述"""
        return self.schema.description

    @property
    def triggers(self) -> list[str]:
        """获取触发关键词列表"""
        return self.schema.triggers

    @abstractmethod
    def _build_schema(self) -> SkillSchema:
        """
        构建技能 Schema

        Returns:
            SkillSchema 对象
        """
        pass

    @abstractmethod
    def execute(self, params: dict[str, Any], context: dict[str, Any]) -> SkillResult:
        """
        执行技能

        Args:
            params: 技能参数
            context: 执行上下文 (包含 agent, memory, tools 等)

        Returns:
            SkillResult 对象
        """
        pass

    def match(self, text: str) -> bool:
        """
        检查文本是否匹配技能触发词

        Args:
            text: 用户输入文本

        Returns:
            是否匹配
        """
        text_lower = text.lower()
        return any(trigger.lower() in text_lower for trigger in self.triggers)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name='{self.name}' triggers={self.triggers}>"
