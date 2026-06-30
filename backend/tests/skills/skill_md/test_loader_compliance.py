"""Integration tests for SkillMdHotLoader spec compliance (Task 4 + Task 5)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from backend.skills.registry import SkillRegistry
from backend.skills.skill_md.loader import SkillMdHotLoader


@pytest.fixture
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
