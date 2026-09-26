"""
技能系统初始化

提供所有内置技能的注册函数和技能发现服务
"""

from .base import BaseSkill, SkillResult, SkillSchema
from .builtin.coder import CoderSkill
from .builtin.search import SearchSkill
from .builtin.travel import TravelSkill
from .builtin.writer import WriterSkill
from .discovery import (
    SkillDiscoveryError,
    SkillDiscoveryService,
    SkillMetadata,
    SkillNotFoundError,
    get_skill_discovery_service,
)
from .enhanced_registry import (
    DiscoveredSkill,
    EnhancedSkillRegistry,
    get_enhanced_skill_registry,
)
from .registry import SkillRegistry
from .skill_md import register_skill_md_skills  # noqa: F401 — re-export 给上层调用


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
    "SkillRegistry",
    "BaseSkill",
    "SkillSchema",
    "SkillResult",
    "SearchSkill",
    "WriterSkill",
    "CoderSkill",
    "TravelSkill",
    "register_all_skills",
    "register_skill_md_skills",
    # Discovery
    "SkillDiscoveryService",
    "SkillMetadata",
    "SkillDiscoveryError",
    "SkillNotFoundError",
    "get_skill_discovery_service",
    # Enhanced Registry
    "EnhancedSkillRegistry",
    "DiscoveredSkill",
    "get_enhanced_skill_registry",
]
