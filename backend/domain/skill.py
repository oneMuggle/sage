"""技能领域模型（纯，零外部依赖）。

仅承载技能的规格与执行结果数据。``BaseSkill`` 抽象与实现保留在
``backend.skills`` 中。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SkillSpec:
    """技能规格。

    Attributes:
        name:        技能名（唯一）
        description: 技能描述
        triggers:    匹配的触发词列表（小写匹配）
        parameters:  JSON Schema 格式的参数定义
        examples:    使用示例
    """

    name: str
    description: str
    triggers: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    examples: List[str] = field(default_factory=list)


@dataclass
class SkillResult:
    """技能执行结果。

    Attributes:
        success:  是否成功
        content:  返回内容（结构化或文本）
        metadata: 附加元数据
        error:    失败时的错误描述
    """

    success: bool
    content: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
