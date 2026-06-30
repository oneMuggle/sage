"""Integration tests for SkillMdHotLoader spec compliance (Task 4 + Task 5)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from backend.skills.registry import SkillRegistry
from backend.skills.skill_md.loader import SkillMdHotLoader


@pytest.fixture()
def tmp_skills_dir(tmp_path: Path) -> Path:
    """返回临时 skills 根目录。"""
    return tmp_path


def test_load_with_license_field(tmp_skills_dir: Path, caplog):
    skill_dir = tmp_skills_dir / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: my-skill\n"
        "description: A tool that does X\n"
        "license: MIT\n"
        "---\n"
        "body",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    with caplog.at_level(logging.WARNING):
        loader = SkillMdHotLoader(registry, dirs=[tmp_skills_dir])
        loaded, _ = loader.scan_and_load()
    assert loaded == 1
    skill = registry.get("my-skill")
    assert skill._doc.license == "MIT"


def test_load_with_compatibility_field(tmp_skills_dir: Path):
    skill_dir = tmp_skills_dir / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: my-skill\n"
        "description: A tool that does X\n"
        "compatibility: Requires Python 3.10+\n"
        "---\n"
        "body",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_skills_dir])
    loaded, _ = loader.scan_and_load()
    assert loaded == 1
    assert registry.get("my-skill")._doc.compatibility == "Requires Python 3.10+"


def test_load_with_allowed_tools_field(tmp_skills_dir: Path):
    skill_dir = tmp_skills_dir / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: my-skill\n"
        "description: A tool that does X\n"
        "allowed-tools: Bash Read Write\n"
        "---\n"
        "body",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_skills_dir])
    loaded, _ = loader.scan_and_load()
    assert loaded == 1
    assert registry.get("my-skill")._doc.allowed_tools == ("Bash", "Read", "Write")


def test_name_mismatch_with_parent_dir_warns(tmp_skills_dir: Path, caplog):
    """name != parent_dir.name 时 WARNING,不阻断加载。"""
    skill_dir = tmp_skills_dir / "search"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: coder-search\n"
        "description: Use this when searching code\n"
        "---\n"
        "body",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    with caplog.at_level(logging.WARNING):
        loader = SkillMdHotLoader(registry, dirs=[tmp_skills_dir])
        loaded, _ = loader.scan_and_load()
    assert loaded == 1  # 不阻断
    assert "agentskills.io spec recommends" in caplog.text
    assert "coder-search" in caplog.text
    assert "search" in caplog.text


# ---- single-file form (Task 5) ----


def test_load_single_file_form_skill_md(tmp_skills_dir: Path, caplog):
    """<dir>/SKILL.md 单文件形态加载(新能力)。"""
    (tmp_skills_dir / "SKILL.md").write_text(
        "---\n"
        "name: root-skill\n"
        "description: Use this single-file root skill\n"
        "---\n"
        "body",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    with caplog.at_level(logging.WARNING):
        loader = SkillMdHotLoader(registry, dirs=[tmp_skills_dir])
        loaded, _ = loader.scan_and_load()
    assert loaded == 1
    skill = registry.get("root-skill")
    assert skill is not None
    # 预期内 warning (parent dir != name)
    assert "agentskills.io spec recommends" in caplog.text


def test_single_file_form_lower_priority_than_subdir(tmp_skills_dir: Path):
    """当同名前后冲突,子目录形态优先(builtin 名称 > 子目录 > 单文件)。"""
    sub = tmp_skills_dir / "my-skill"
    sub.mkdir()
    (sub / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: Use this subdir form\n---\nbody",
        encoding="utf-8",
    )
    (tmp_skills_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: Use this single-file form\n---\nbody",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_skills_dir])
    loaded, _ = loader.scan_and_load()
    assert loaded == 1
    # 子目录形态胜(loaded first): 用 description 区分两个形态,body 都是占位 "body"
    assert "subdir form" in registry.get("my-skill")._doc.description


def test_existing_skills_still_load_compatible(tmp_skills_dir: Path):
    """现有 SKILL.md 无新字段,继续正常加载(向后兼容)。"""
    skill_dir = tmp_skills_dir / "legacy-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: legacy-skill\n"
        "description: Use this when you need legacy behavior\n"
        "triggers:\n  - legacy\n  - old\n"
        "version: 0.5.0\n"
        "metadata:\n  author: sage\n"
        "---\n"
        "Legacy body",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_skills_dir])
    loaded, _ = loader.scan_and_load()
    assert loaded == 1
    doc = registry.get("legacy-skill")._doc
    assert doc.license is None
    assert doc.compatibility is None
    assert doc.allowed_tools == ()
    assert doc.triggers == ["legacy", "old"]
    assert doc.version == "0.5.0"
    assert doc.metadata == {"author": "sage"}


def test_no_license_field_loaded_as_none(tmp_skills_dir: Path):
    """无 license 字段 → doc.license is None。"""
    skill_dir = tmp_skills_dir / "no-license"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: no-license\ndescription: A tool without license field\n---\nbody",
        encoding="utf-8",
    )
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_skills_dir])
    loaded, _ = loader.scan_and_load()
    assert loaded == 1
    assert registry.get("no-license")._doc.license is None
