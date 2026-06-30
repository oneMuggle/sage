"""SKILL.md 技能删除器。

物理 unlink ``<base_dir>/<skill_name>/`` 目录 + 从 SkillRegistry unregister。

设计要点：
- 仅限 SKILL.md (source='skillmd') 用户技能。builtin 永远拒绝。
- name 校验：^[a-z0-9-]{1,64}$。
- base_dir 必须在 SAGE_SKILLS_DIR 之下 (防御 `..` 路径遍历)。
- 删失败 (rmtree OSError) → 整体抛 + 不动 registry。
- 删成功 → 改 registry (unregister) + logger.warning 审计。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from typing import TypedDict

from ..registry import SkillRegistry

logger = logging.getLogger(__name__)

_SKILL_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")


class BuiltinSkillError(ValueError):
    """试图删除 builtin (source='builtin') 技能时抛。"""


class SkillMdNotFoundError(FileNotFoundError):
    """试图删除不存在的 skill 时抛。"""


class DeleteSkillResult(TypedDict, total=False):
    """删除结果。"""

    deleted: bool
    name: str
    base_dir: str


class SkillMdDeleter:
    """物理删除一个 SKILL.md 技能 + 从 registry 注销。"""

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        skills_dir: Path | None = None,
    ) -> None:
        self._registry = registry
        # skills_dir 解析延迟到 delete() 时 (避免 builtin-blocked 路径上
        # 解析失败; 也让 __init__ 在缺 SAGE_SKILLS_DIR 时不抛异常)。
        self._explicit_skills_dir = skills_dir

    def _resolve_skills_dir(self) -> Path:
        """解析 skills_dir: 显式参数 > SAGE_SKILLS_DIR > ./skills > ~/.sage/skills。"""
        if self._explicit_skills_dir is not None:
            return self._explicit_skills_dir
        env = os.environ.get("SAGE_SKILLS_DIR", "").strip()
        if env:
            p = Path(env).expanduser().resolve()
            if p.is_dir():
                return p
        cwd_skills = Path.cwd() / "skills"
        if cwd_skills.is_dir():
            return cwd_skills.resolve()
        home_skills = Path.home() / ".sage" / "skills"
        if home_skills.is_dir():
            return home_skills.resolve()
        raise FileNotFoundError(
            "No SAGE_SKILLS_DIR / ./skills / ~/.sage/skills found; cannot resolve delete target"
        )

    def delete(self, name: str) -> DeleteSkillResult:
        if not _SKILL_NAME_RE.match(name):
            raise ValueError(
                f"Invalid skill name {name!r}: must match ^[a-z0-9-]{{1,64}}$"
            )

        # builtin 检测：registry 里有同名 schema 且不是 SkillMdSkill 实例
        # 此 check 在文件系统解析前 → builtin-blocked 测试不需要 skills_dir。
        if self._registry.exists(name) and self._is_builtin(name):
            raise BuiltinSkillError(
                f"Cannot delete builtin skill {name!r}; builtin skills are read-only"
            )

        skills_dir = self._resolve_skills_dir()
        target = (skills_dir / name).resolve()
        self._validate_path_under_skills_dir(target, skills_dir)

        if not target.exists():
            raise SkillMdNotFoundError(
                f"SKILL.md skill {name!r} not found at {target}"
            )

        # Step: 物理删除 + registry 注销。rmtree 失败时不改 registry。
        shutil.rmtree(target)
        if self._registry.exists(name):
            self._registry.unregister(name)

        logger.warning(
            "Deleted SKILL.md skill: name=%s base_dir=%s", name, target
        )

        return DeleteSkillResult(
            deleted=True,
            name=name,
            base_dir=str(target),
        )

    def _validate_path_under_skills_dir(self, target: Path, skills_dir: Path) -> None:
        """防御性: target 必须在 skills_dir 之下 (或等于)。"""
        try:
            target.relative_to(skills_dir.resolve())
        except ValueError as e:
            raise ValueError(
                f"Refusing to delete {target}: outside skills_dir {skills_dir}"
            ) from e

    def _is_builtin(self, name: str) -> bool:
        """通过 introspect registry 内部判定 skill 是否 builtin。

        Strategy: 用 ``registry.get(name)`` 拿到 BaseSkill 实例,
        通过 ``isinstance(instance, SkillMdSkill)`` 判定。
        SkillMdSkill 实例来自 SKILL.md 加载,其他 BaseSkill 子类是 builtin。
        """
        try:
            instance = self._registry.get(name)
            if instance is None:
                # registry.exists 已 guard; 此处兜底,假设 builtin
                return True
            from .skill import SkillMdSkill  # noqa: PLC0415

            return not isinstance(instance, SkillMdSkill)
        except Exception:  # noqa: BLE001
            # 最保守的兜底: 假设 builtin 在 registry 且没被 register_skill_md 改写
            return True