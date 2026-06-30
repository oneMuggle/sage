"""Tests for SkillMdDocument dataclass (Task 3: new spec fields)."""

from __future__ import annotations

from backend.skills.skill_md.skill import SkillMdDocument


def test_default_license_is_none():
    doc = SkillMdDocument(name="x", description="A tool")
    assert doc.license is None


def test_default_compatibility_is_none():
    doc = SkillMdDocument(name="x", description="A tool")
    assert doc.compatibility is None


def test_default_allowed_tools_is_empty_tuple():
    doc = SkillMdDocument(name="x", description="A tool")
    assert doc.allowed_tools == ()


def test_set_new_fields():
    doc = SkillMdDocument(
        name="x",
        description="A tool",
        license="MIT",
        compatibility="Requires Python 3.10+",
        allowed_tools=("Bash", "Read", "Write"),
    )
    assert doc.license == "MIT"
    assert doc.compatibility == "Requires Python 3.10+"
    assert doc.allowed_tools == ("Bash", "Read", "Write")


def test_existing_fields_still_work():
    """向后兼容: 现有 8 个 sage 扩展字段仍正常初始化。"""
    doc = SkillMdDocument(
        name="x",
        description="A tool",
        triggers=["x", "xtra"],
        version="1.2.3",
        metadata={"author": "sage"},
    )
    assert doc.triggers == ["x", "xtra"]
    assert doc.version == "1.2.3"
    assert doc.metadata == {"author": "sage"}