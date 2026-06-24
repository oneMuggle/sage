"""技能调用端口。

技能（Skill）相比工具粒度更粗：每个技能是 LLM 可用的"工作流"，
通常由一组工具调用 + 提示词模板组成。本接口用于发现和触发技能。
"""

from __future__ import annotations

from typing import Any, Protocol

from sage_core import SkillResult, SkillSpec


class SkillPort(Protocol):
    """技能发现与执行端口。"""

    def list_skills(self) -> list[SkillSpec]:
        """列出当前可用的所有技能规格。"""
        ...

    async def execute(
        self,
        name: str,
        action: str,
        args: dict[str, Any],
    ) -> SkillResult:
        """按名称与动作执行技能。

        Args:
            name:   技能名（需事先 ``register`` 过）。
            action: 技能子动作（同一技能可能暴露多个入口）。
            args:   技能参数。

        Returns:
            ``SkillResult``；失败时 ``success=False`` 并携带 ``error``。
        """
        ...
