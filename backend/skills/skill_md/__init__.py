"""SKILL.md 适配层包。

加载 AgentSkills 规范 (agentskills.io) 的 markdown 形式技能,与 Python builtin
技能共享 ``SkillRegistry``。实现细节见 ``.frontmatter`` / ``.skill`` /
``.loader`` / ``.validation`` / ``.gating``。
"""

from .frontmatter import SkillMdParseError, dump, parse, parse_file
from .gating import GatingContext, GatingResult, build_gating_context, evaluate_gating
from .loader import (
    SkillMdHotLoader,
    discover_skill_md_dirs,
    register_skill_md_skills,
)
from .skill import DispatchMode, RequiresSpec, SkillMdDocument, SkillMdSkill
from .validation import (
    SkillMdSecurityError,
    sanitize_for_logging,
    validate_base_dir,
)

__all__ = [
    "SkillMdParseError",
    "dump",
    "parse",
    "parse_file",
    "DispatchMode",
    "GatingContext",
    "GatingResult",
    "RequiresSpec",
    "SkillMdDocument",
    "SkillMdSkill",
    "SkillMdHotLoader",
    "build_gating_context",
    "discover_skill_md_dirs",
    "evaluate_gating",
    "register_skill_md_skills",
    "SkillMdSecurityError",
    "sanitize_for_logging",
    "validate_base_dir",
]
