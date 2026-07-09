"""SKILL.md importer / writer 专属异常。"""

from __future__ import annotations


class NoSkillsDirError(RuntimeError):
    """无法解析或创建 skills_dir(SAGE_SKILLS_DIR / ~/.sage/skills 都不可用)。"""


class WriteFailedError(OSError):
    """写 SKILL.md 时底层 OSError (PermissionError / DiskFull / 等)。"""


class ImportValidationError(ValueError):
    """name 不符合 slug、frontmatter 缺字段等单文件校验失败。"""
