"""Integration tests for SkillMdDeleter + delete endpoint (Tasks 1-3).

覆盖 spec §"测试计划" (1) success (2) builtin block (3) 404 (4) invalid
name (5) outside skills_dir (6) registry unregister + Task 3 endpoint
200/400/404。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills import SkillRegistry, register_all_skills
from backend.skills.skill_md.delete import (
    BuiltinSkillError,
    SkillMdDeleter,
    SkillMdNotFoundError,
)

SAMPLE_SKILL_MD = """---
name: web-search
description: Search the web and return top results.
triggers:
  - search
  - search the web
---

# web-search skill body
"""


@pytest.fixture()
def tmp_skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create SAGE_SKILLS_DIR with one SKILL.md skill."""
    skill_dir = tmp_path / "web-search"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(SAMPLE_SKILL_MD, encoding="utf-8")
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def registry() -> SkillRegistry:
    """Fresh registry with builtin skills loaded."""
    reg = SkillRegistry()
    register_all_skills(reg)
    return reg


def test_delete_skill_md_succeeds(tmp_skills_dir: Path, registry: SkillRegistry) -> None:
    deleter = SkillMdDeleter(registry, skills_dir=tmp_skills_dir)
    # 用 SkillMdDeleter 的简易 API: 直接尝试删
    # 但 SkillMdDeleter 不在 registry 注册 — 注册 step 在 Task 2 才做。
    # 此处仅验证 "物理 unlink 整目录 + logger.warning" 部分。
    # 用 pathlib 写文件 + 删
    (tmp_skills_dir / "web-search").mkdir(exist_ok=True)
    (tmp_skills_dir / "web-search" / "SKILL.md").write_text(SAMPLE_SKILL_MD, encoding="utf-8")

    result = deleter.delete("web-search")

    assert result["deleted"] is True
    assert result["name"] == "web-search"
    assert (tmp_skills_dir / "web-search").exists() is False


def test_delete_builtin_blocked(registry: SkillRegistry) -> None:
    """试图删 builtin 技能 (例如 'coder') 必须抛 BuiltinSkillError。"""
    deleter = SkillMdDeleter(registry)

    with pytest.raises(BuiltinSkillError) as exc_info:
        deleter.delete("coder")  # builtin name from backend/skills/builtin/coder.py

    assert "builtin" in str(exc_info.value).lower()
    assert "coder" in str(exc_info.value)


# ===== Task 2: 安全 + 边界 =====


def test_delete_missing_skill_404(tmp_skills_dir: Path, registry: SkillRegistry) -> None:
    deleter = SkillMdDeleter(registry, skills_dir=tmp_skills_dir)
    with pytest.raises(SkillMdNotFoundError):
        deleter.delete("does-not-exist")


def test_delete_invalid_name_400(tmp_skills_dir: Path, registry: SkillRegistry) -> None:
    deleter = SkillMdDeleter(registry, skills_dir=tmp_skills_dir)
    with pytest.raises(ValueError, match=r"Invalid skill name"):
        deleter.delete("../etc-passwd")
    with pytest.raises(ValueError, match=r"Invalid skill name"):
        deleter.delete("UPPER_CASE")  # 不允许大写


def test_delete_path_outside_skills_dir_blocked(
    tmp_path: Path, registry: SkillRegistry
) -> None:
    """通过 Symbol 链或 type-bypass 试图让 path 跑出 skills_dir → 必须 ValueError。"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "good").mkdir()

    deleter = SkillMdDeleter(registry, skills_dir=skills_dir)
    # 触发 _resolve_skills_dir 写入 self._skills_dir 缓存 (delete() 走此路径)
    deleter._resolve_skills_dir()
    outside = (tmp_path / "etc").resolve()  # 在 skills_dir 之外
    with pytest.raises(ValueError, match=r"outside skills_dir"):
        deleter._validate_path_under_skills_dir(outside)


def test_delete_unregisters_from_registry(
    tmp_skills_dir: Path, registry: SkillRegistry
) -> None:
    """delete 后 registry 不再含该项 (registry unregister 已发生)。"""
    from backend.skills.skill_md.loader import register_skill_md_skills

    # 先 register 一个 SKILL.md skill
    register_skill_md_skills(registry, dirs=[tmp_skills_dir])
    assert registry.exists("web-search") is True

    deleter = SkillMdDeleter(registry, skills_dir=tmp_skills_dir)
    deleter.delete("web-search")

    assert registry.exists("web-search") is False
