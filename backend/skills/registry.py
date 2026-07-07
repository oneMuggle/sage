"""
技能注册表
管理所有可用技能的注册、匹配和执行
"""

from __future__ import annotations

import builtins
import logging
from typing import Dict, List

from .base import BaseSkill, SkillResult, SkillSchema

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    技能注册表

    负责:
    - 注册和取消注册技能
    - 根据名称或触发词获取技能
    - 列出所有可用技能
    """

    def __init__(self):
        self._skills: Dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill) -> None:
        """
        注册技能

        Args:
            skill: BaseSkill 实例
        """
        skill_name = skill.name
        if skill_name in self._skills:
            logger.warning(f"技能 {skill_name} 已存在，将被覆盖")

        self._skills[skill_name] = skill
        logger.info(f"注册技能: {skill_name}")

    def unregister(self, name: str) -> bool:
        """
        取消注册技能

        Args:
            name: 技能名称

        Returns:
            是否成功取消
        """
        if name in self._skills:
            del self._skills[name]
            logger.info(f"取消注册技能: {name}")
            return True
        return False

    def get(self, name: str) -> BaseSkill | None:
        """
        获取技能

        Args:
            name: 技能名称

        Returns:
            技能实例，不存在返回 None
        """
        return self._skills.get(name)

    def list(self) -> List[SkillSchema]:
        """
        列出所有已注册技能的 Schema

        Returns:
            技能 Schema 列表
        """
        return [skill.schema for skill in self._skills.values()]

    def list_names(self) -> builtins.list[str]:
        """
        列出所有已注册技能的名称

        Returns:
            技能名称列表
        """
        return list(self._skills.keys())

    def match(self, text: str) -> BaseSkill | None:
        """
        查找匹配的技能（第一个匹配）

        Args:
            text: 用户输入文本

        Returns:
            匹配的技能实例，没有匹配返回 None
        """
        for skill in self._skills.values():
            if skill.match(text):
                return skill
        return None

    def match_all(self, text: str) -> builtins.list[BaseSkill]:
        """
        查找所有匹配的技能

        Args:
            text: 用户输入文本

        Returns:
            所有匹配的技能列表
        """
        return [skill for skill in self._skills.values() if skill.match(text)]

    def execute(self, text: str, params: dict, context: dict) -> SkillResult | None:
        """
        匹配并执行技能

        Args:
            text: 用户输入文本
            params: 技能参数
            context: 执行上下文

        Returns:
            技能执行结果，没有匹配返回 None
        """
        skill = self.match(text)
        if skill is None:
            return None

        try:
            return skill.execute(params, context)
        except Exception as e:
            logger.error(f"技能执行失败: {skill.name}, error: {str(e)}")
            return SkillResult(success=False, error=f"技能执行失败: {str(e)}")

    def exists(self, name: str) -> bool:
        """
        检查技能是否已注册

        Args:
            name: 技能名称

        Returns:
            是否存在
        """
        return name in self._skills

    def clear(self) -> None:
        """清空所有已注册技能"""
        self._skills.clear()
        logger.info("清空所有已注册技能")
