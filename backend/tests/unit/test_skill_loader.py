"""Unit tests for SkillLoader (skill file writer).

Tests the ``write()`` method and directory resolution logic.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.loader import SkillLoader, get_skill_loader, reset_skill_loader


@pytest.mark.skipif(not hasattr(__import__("os"), "symlink"), reason="symlink unsupported")
def test_write_rejects_symlinked_skill_directory(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "evil").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError, match="symlink"):
        SkillLoader(skills_dir=skills_dir).write("evil", "secret")
    assert not (outside / "SKILL.md").exists()


@pytest.mark.skipif(not hasattr(__import__("os"), "symlink"), reason="symlink unsupported")
def test_write_rejects_symlinked_skill_file(tmp_path: Path):
    outside = tmp_path / "outside.md"
    outside.write_text("original", encoding="utf-8")
    skills_dir = tmp_path / "skills"
    (skills_dir / "evil").mkdir(parents=True)
    (skills_dir / "evil" / "SKILL.md").symlink_to(outside)

    with pytest.raises(OSError, match="symlink"):
        SkillLoader(skills_dir=skills_dir).write("evil", "secret")
    assert outside.read_text(encoding="utf-8") == "original"


@pytest.fixture()
def skills_dir(tmp_path: Path) -> Path:
    """A temporary skills directory."""
    return tmp_path / "skills"


@pytest.fixture()
def loader(skills_dir: Path) -> SkillLoader:
    """A SkillLoader backed by the temp directory."""
    return SkillLoader(skills_dir=skills_dir)


@pytest.mark.skipif(not hasattr(__import__("os"), "symlink"), reason="symlink unsupported")
def test_write_rejects_symlinked_root(tmp_path: Path):
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    skills_dir = tmp_path / "skills"
    skills_dir.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(OSError, match="symlink"):
        SkillLoader(skills_dir=skills_dir).write("evil", "secret")
    assert not (real_root / "evil" / "SKILL.md").exists()


class TestSkillLoaderWrite:
    """write() method tests."""

    def test_write_creates_directory_and_file(self, loader: SkillLoader, skills_dir: Path):
        """write() creates <name>/SKILL.md with the given content."""
        path = loader.write("my-skill", "# My Skill\n\nContent here.")
        assert path == skills_dir / "my-skill" / "SKILL.md"
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "# My Skill\n\nContent here."

    def test_write_overwrites_existing(self, loader: SkillLoader):
        """write() overwrites an existing SKILL.md by default for compatibility."""
        loader.write("dup-skill", "v1")
        path = loader.write("dup-skill", "v2")
        assert path.read_text(encoding="utf-8") == "v2"

    def test_write_without_overwrite_rejects_existing_file(self, loader: SkillLoader):
        """Safe writes reject an existing file without changing its contents."""
        path = loader.write("dup-skill", "v1")

        with pytest.raises(FileExistsError):
            loader.write("dup-skill", "v2", overwrite=False)

        assert path.read_text(encoding="utf-8") == "v1"

    def test_write_without_overwrite_creates_new_file(self, loader: SkillLoader):
        """Safe writes still create a new skill file."""
        path = loader.write("new-skill", "v1", overwrite=False)

        assert path.read_text(encoding="utf-8") == "v1"

    def test_write_invalid_name_empty(self, loader: SkillLoader):
        """write() raises ValueError for empty name."""
        with pytest.raises(ValueError, match="Invalid skill name"):
            loader.write("", "content")

    def test_write_invalid_name_slash(self, loader: SkillLoader):
        """write() raises ValueError for name containing slash."""
        with pytest.raises(ValueError, match="Invalid skill name"):
            loader.write("bad/name", "content")

    def test_write_invalid_name_dotdot(self, loader: SkillLoader):
        """write() raises ValueError for '..'."""
        with pytest.raises(ValueError, match="Invalid skill name"):
            loader.write("..", "content")

    def test_write_invalid_name_dot(self, loader: SkillLoader):
        """write() raises ValueError for '.'."""
        with pytest.raises(ValueError, match="Invalid skill name"):
            loader.write(".", "content")


class TestGetSkillLoaderSingleton:
    """Singleton pattern tests."""

    def setup_method(self):
        reset_skill_loader()

    def teardown_method(self):
        reset_skill_loader()

    def test_returns_same_instance(self):
        """get_skill_loader() returns the same instance on repeated calls."""
        a = get_skill_loader()
        b = get_skill_loader()
        assert a is b

    def test_reset_clears_singleton(self):
        """reset_skill_loader() causes next get to create a new instance."""
        a = get_skill_loader()
        reset_skill_loader()
        b = get_skill_loader()
        assert a is not b
