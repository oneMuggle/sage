"""
技能系统初始化

提供所有内置技能的注册函数
"""
from .registry import SkillRegistry
from .base import BaseSkill, SkillSchema, SkillResult
from .builtin.search import SearchSkill
from .builtin.writer import WriterSkill
from .builtin.coder import CoderSkill
from .builtin.travel import TravelSkill


def register_all_skills(registry: SkillRegistry) -> None:
    """
    注册所有内置技能到注册表
    
    Args:
        registry: 技能注册表
    """
    registry.register(SearchSkill())
    registry.register(WriterSkill())
    registry.register(CoderSkill())
    registry.register(TravelSkill())


__all__ = [
    'SkillRegistry',
    'BaseSkill',
    'SkillSchema',
    'SkillResult',
    'SearchSkill',
    'WriterSkill',
    'CoderSkill',
    'TravelSkill',
    'register_all_skills',
]
