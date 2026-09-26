"""
Unit tests for skill discovery service.

Tests cover:
- SKILL.md file discovery and parsing
- Frontmatter extraction
- Cache invalidation
- Error handling

Author: Claude
Date: 2026-09-26
"""

import tempfile
from pathlib import Path

import pytest

from backend.skills.discovery import (
    SkillDiscoveryError,
    SkillDiscoveryService,
    SkillMetadata,
    SkillNotFoundError,
)


class TestSkillMetadata:
    """Tests for SkillMetadata model."""

    def test_create_metadata(self):
        """Test creating skill metadata."""
        metadata = SkillMetadata(
            name="test-skill",
            description="A test skill",
            version="1.0.0",
            author="Test Author",
            tags=["test", "demo"],
            path="/path/to/SKILL.md",
            skill_dir="/path/to",
        )
        assert metadata.name == "test-skill"
        assert metadata.version == "1.0.0"
        assert "test" in metadata.tags


class TestSkillDiscoveryService:
    """Tests for SkillDiscoveryService."""

    @pytest.fixture
    def skills_dir(self, tmp_path):
        """Create a temporary skills directory."""
        return tmp_path / "skills"

    @pytest.fixture
    def service(self, skills_dir):
        """Create a test discovery service."""
        return SkillDiscoveryService(skills_dir=skills_dir)

    def create_skill(self, skills_dir, name, content):
        """Helper to create a test skill."""
        skill_dir = skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        return skill_dir

    def test_discover_empty_directory(self, service, skills_dir):
        """Test discovering from empty directory."""
        skills_dir.mkdir(parents=True, exist_ok=True)
        skills = service.discover_all()
        assert len(skills) == 0

    def test_discover_nonexistent_directory(self, tmp_path):
        """Test discovering from nonexistent directory."""
        nonexistent = tmp_path / "nonexistent"
        service = SkillDiscoveryService(skills_dir=nonexistent)
        skills = service.discover_all()
        assert len(skills) == 0

    def test_discover_single_skill(self, service, skills_dir):
        """Test discovering a single skill."""
        skills_dir.mkdir(parents=True, exist_ok=True)

        skill_content = """---
name: test-skill
description: A test skill
version: 1.0.0
author: Test Author
tags: test, demo
---

# Test Skill

Content here.
"""
        self.create_skill(skills_dir, "test-skill", skill_content)

        skills = service.discover_all()
        assert len(skills) == 1
        assert skills[0].name == "test-skill"
        assert skills[0].description == "A test skill"
        assert skills[0].version == "1.0.0"

    def test_discover_multiple_skills(self, service, skills_dir):
        """Test discovering multiple skills."""
        skills_dir.mkdir(parents=True, exist_ok=True)

        self.create_skill(
            skills_dir,
            "skill-1",
            "---\nname: skill-1\n---\n# Skill 1\n",
        )
        self.create_skill(
            skills_dir,
            "skill-2",
            "---\nname: skill-2\n---\n# Skill 2\n",
        )

        skills = service.discover_all()
        assert len(skills) == 2
        names = [s.name for s in skills]
        assert "skill-1" in names
        assert "skill-2" in names

    def test_discover_one_skill(self, service, skills_dir):
        """Test discovering a specific skill."""
        skills_dir.mkdir(parents=True, exist_ok=True)

        self.create_skill(
            skills_dir,
            "target-skill",
            "---\nname: target-skill\ndescription: Target\n---\n# Target\n",
        )

        metadata = service.discover_one("target-skill")
        assert metadata.name == "target-skill"
        assert metadata.description == "Target"

    def test_discover_one_not_found(self, service, skills_dir):
        """Test discovering nonexistent skill raises error."""
        skills_dir.mkdir(parents=True, exist_ok=True)

        with pytest.raises(SkillNotFoundError, match="技能未找到"):
            service.discover_one("nonexistent")

    def test_parse_frontmatter(self, service, skills_dir):
        """Test parsing SKILL.md frontmatter."""
        skills_dir.mkdir(parents=True, exist_ok=True)

        skill_content = """---
name: my-skill
description: My skill description
version: 2.1.0
author: John Doe
tags: productivity, tools
triggers: test, example
priority: 10
---

# My Skill

Content.
"""
        self.create_skill(skills_dir, "my-skill", skill_content)

        metadata = service.discover_one("my-skill")
        assert metadata.name == "my-skill"
        assert metadata.description == "My skill description"
        assert metadata.version == "2.1.0"
        assert metadata.author == "John Doe"
        assert "productivity" in metadata.tags
        assert "tools" in metadata.tags
        assert "test" in metadata.triggers
        assert metadata.priority == 10

    def test_parse_without_frontmatter(self, service, skills_dir):
        """Test parsing SKILL.md without frontmatter."""
        skills_dir.mkdir(parents=True, exist_ok=True)

        skill_content = """# My Skill

This is the first paragraph.

Second paragraph.
"""
        self.create_skill(skills_dir, "my-skill", skill_content)

        metadata = service.discover_one("my-skill")
        assert metadata.name == "my-skill"  # From directory name
        assert metadata.description == "This is the first paragraph."
        assert metadata.version == "1.0.0"  # Default

    def test_cache_invalidation(self, service, skills_dir):
        """Test cache invalidation."""
        skills_dir.mkdir(parents=True, exist_ok=True)

        self.create_skill(
            skills_dir, "skill-1", "---\nname: skill-1\n---\n# Skill 1\n"
        )

        # First discovery populates cache
        skills1 = service.discover_all()
        assert len(skills1) == 1

        # Add another skill
        self.create_skill(
            skills_dir, "skill-2", "---\nname: skill-2\n---\n# Skill 2\n"
        )

        # Cache should still return 1
        skills2 = service.discover_all(use_cache=True)
        assert len(skills2) == 1

        # Invalidate cache
        service.invalidate_cache()

        # Now should return 2
        skills3 = service.discover_all()
        assert len(skills3) == 2

    def test_list_skill_names(self, service, skills_dir):
        """Test listing skill names."""
        skills_dir.mkdir(parents=True, exist_ok=True)

        self.create_skill(
            skills_dir, "skill-a", "---\nname: skill-a\n---\n# A\n"
        )
        self.create_skill(
            skills_dir, "skill-b", "---\nname: skill-b\n---\n# B\n"
        )

        names = service.list_skill_names()
        assert "skill-a" in names
        assert "skill-b" in names

    def test_has_skill(self, service, skills_dir):
        """Test checking skill existence."""
        skills_dir.mkdir(parents=True, exist_ok=True)

        self.create_skill(
            skills_dir, "existing", "---\nname: existing\n---\n# Existing\n"
        )

        assert service.has_skill("existing")
        assert not service.has_skill("nonexistent")

    def test_get_skill_content(self, service, skills_dir):
        """Test getting skill content."""
        skills_dir.mkdir(parents=True, exist_ok=True)

        content = "---\nname: test\n---\n# Test Skill\n\nContent here."
        self.create_skill(skills_dir, "test", content)

        result = service.get_skill_content("test")
        assert "Test Skill" in result
        assert "Content here" in result

    def test_get_skill_content_not_found(self, service, skills_dir):
        """Test getting content of nonexistent skill raises error."""
        skills_dir.mkdir(parents=True, exist_ok=True)

        with pytest.raises(SkillNotFoundError, match="技能未找到"):
            service.get_skill_content("nonexistent")

    def test_default_skills_dir(self):
        """Test default skills directory."""
        service = SkillDiscoveryService()
        # Should be ~/.sage/skills
        assert str(service.skills_dir).endswith(".sage/skills")

    def test_custom_skills_dir(self, tmp_path):
        """Test custom skills directory."""
        custom_dir = tmp_path / "custom"
        service = SkillDiscoveryService(skills_dir=custom_dir)
        assert service.skills_dir == custom_dir

    def test_environment_variable_skills_dir(self, tmp_path, monkeypatch):
        """Test SAGE_SKILLS_DIR environment variable."""
        custom_dir = tmp_path / "env-skills"
        monkeypatch.setenv("SAGE_SKILLS_DIR", str(custom_dir))

        service = SkillDiscoveryService()
        assert service.skills_dir == custom_dir

    def test_ignore_non_directory_files(self, service, skills_dir):
        """Test that non-directory files are ignored."""
        skills_dir.mkdir(parents=True, exist_ok=True)

        # Create a file (not directory)
        (skills_dir / "not-a-skill.txt").write_text("Not a skill")

        # Create a valid skill
        self.create_skill(
            skills_dir, "valid-skill", "---\nname: valid-skill\n---\n# Valid\n"
        )

        skills = service.discover_all()
        assert len(skills) == 1
        assert skills[0].name == "valid-skill"

    def test_ignore_directories_without_skill_md(self, service, skills_dir):
        """Test that directories without SKILL.md are ignored."""
        skills_dir.mkdir(parents=True, exist_ok=True)

        # Create directory without SKILL.md
        (skills_dir / "no-skill-here").mkdir()

        # Create valid skill
        self.create_skill(
            skills_dir, "valid", "---\nname: valid\n---\n# Valid\n"
        )

        skills = service.discover_all()
        assert len(skills) == 1


class TestSkillDiscoveryErrors:
    """Tests for discovery error handling."""

    def test_parse_malformed_frontmatter(self, tmp_path):
        """Test parsing malformed frontmatter doesn't crash."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "malformed"
        skill_dir.mkdir()

        # Malformed YAML (but valid markdown)
        content = "---\nname: test\ninvalid yaml here\n---\n# Test\n"
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        service = SkillDiscoveryService(skills_dir=skills_dir)
        # Should not crash, just parse what it can
        skills = service.discover_all()
        assert len(skills) == 1

    def test_parse_empty_file(self, tmp_path):
        """Test parsing empty SKILL.md."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "empty"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("", encoding="utf-8")

        service = SkillDiscoveryService(skills_dir=skills_dir)
        skills = service.discover_all()
        assert len(skills) == 1
        # Should use directory name
        assert skills[0].name == "empty"
