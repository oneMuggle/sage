"""
Unit tests for enhanced skill registry.

Tests cover:
- Discovery integration
- Metadata management
- DiscoveredSkill wrapper
- Refresh functionality

Author: Claude
Date: 2026-09-26
"""

import tempfile
from pathlib import Path

import pytest

from backend.skills.discovery import SkillDiscoveryService
from backend.skills.enhanced_registry import (
    DiscoveredSkill,
    EnhancedSkillRegistry,
)


class TestEnhancedSkillRegistry:
    """Tests for EnhancedSkillRegistry."""

    @pytest.fixture
    def skills_dir(self, tmp_path):
        """Create a temporary skills directory."""
        return tmp_path / "skills"

    @pytest.fixture
    def discovery_service(self, skills_dir):
        """Create a test discovery service."""
        skills_dir.mkdir(parents=True, exist_ok=True)
        return SkillDiscoveryService(skills_dir=skills_dir)

    @pytest.fixture
    def registry(self, discovery_service):
        """Create a test enhanced registry."""
        return EnhancedSkillRegistry(discovery_service=discovery_service)

    def create_skill(self, skills_dir, name, content):
        """Helper to create a test skill."""
        skill_dir = skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        return skill_dir

    def test_discover_and_register(self, registry, skills_dir):
        """Test discovering and registering skills."""
        skill_content = """---
name: test-skill
description: A test skill
triggers: test, example
---

# Test Skill

Content.
"""
        self.create_skill(skills_dir, "test-skill", skill_content)

        count = registry.discover_and_register()
        assert count == 1
        assert registry.exists("test-skill")

    def test_discover_multiple(self, registry, skills_dir):
        """Test discovering multiple skills."""
        self.create_skill(
            skills_dir, "skill-1", "---\nname: skill-1\n---\n# Skill 1\n"
        )
        self.create_skill(
            skills_dir, "skill-2", "---\nname: skill-2\n---\n# Skill 2\n"
        )

        count = registry.discover_and_register()
        assert count == 2
        assert registry.exists("skill-1")
        assert registry.exists("skill-2")

    def test_discover_skip_existing(self, registry, skills_dir):
        """Test that discovery skips already registered skills."""
        self.create_skill(
            skills_dir, "test-skill", "---\nname: test-skill\n---\n# Test\n"
        )

        # First discovery
        count1 = registry.discover_and_register()
        assert count1 == 1

        # Second discovery should not register again
        count2 = registry.discover_and_register()
        assert count2 == 0

    def test_get_metadata(self, registry, skills_dir):
        """Test getting skill metadata."""
        skill_content = """---
name: my-skill
description: My skill
version: 2.0.0
author: Test Author
---

# My Skill
"""
        self.create_skill(skills_dir, "my-skill", skill_content)
        registry.discover_and_register()

        metadata = registry.get_metadata("my-skill")
        assert metadata is not None
        assert metadata.name == "my-skill"
        assert metadata.description == "My skill"
        assert metadata.version == "2.0.0"

    def test_get_metadata_not_found(self, registry, skills_dir):
        """Test getting metadata for nonexistent skill."""
        skills_dir.mkdir(parents=True, exist_ok=True)
        metadata = registry.get_metadata("nonexistent")
        assert metadata is None

    def test_list_with_metadata(self, registry, skills_dir):
        """Test listing skills with metadata."""
        self.create_skill(
            skills_dir, "skill-a", "---\nname: skill-a\n---\n# A\n"
        )
        self.create_skill(
            skills_dir, "skill-b", "---\nname: skill-b\n---\n# B\n"
        )

        registry.discover_and_register()

        skills_with_meta = registry.list_with_metadata()
        assert len(skills_with_meta) == 2

        for skill, metadata in skills_with_meta:
            assert skill is not None
            assert metadata is not None

    def test_refresh_discovery(self, registry, skills_dir):
        """Test refreshing discovery."""
        # Initial discovery
        count1 = registry.discover_and_register()
        assert count1 == 0  # No skills yet

        # Add a skill
        self.create_skill(
            skills_dir, "new-skill", "---\nname: new-skill\n---\n# New\n"
        )

        # Refresh should find new skill
        count2 = registry.refresh_discovery()
        assert count2 == 1
        assert registry.exists("new-skill")


class TestDiscoveredSkill:
    """Tests for DiscoveredSkill wrapper."""

    @pytest.fixture
    def skill_metadata(self):
        """Create test skill metadata."""
        from backend.skills.discovery import SkillMetadata

        return SkillMetadata(
            name="test-skill",
            description="A test skill",
            version="1.0.0",
            author="Test Author",
            tags=["test"],
            path="/tmp/test-skill/SKILL.md",
            skill_dir="/tmp/test-skill",
            triggers=["test", "example"],
        )

    @pytest.fixture
    def discovered_skill(self, skill_metadata):
        """Create a test discovered skill."""
        return DiscoveredSkill(skill_metadata)

    def test_name_property(self, discovered_skill):
        """Test name property."""
        assert discovered_skill.name == "test-skill"

    def test_description_property(self, discovered_skill):
        """Test description property."""
        assert discovered_skill.description == "A test skill"

    def test_schema_property(self, discovered_skill):
        """Test schema property."""
        schema = discovered_skill.schema
        assert schema.name == "test-skill"
        assert schema.description == "A test skill"
        assert "test" in schema.triggers

    def test_match_trigger(self, discovered_skill):
        """Test matching against triggers."""
        assert discovered_skill.match("this is a test")
        assert discovered_skill.match("example usage")
        assert not discovered_skill.match("no match here")

    def test_match_name(self, discovered_skill):
        """Test matching against skill name."""
        assert discovered_skill.match("use test-skill")
        assert not discovered_skill.match("use other-skill")

    def test_execute(self, tmp_path, skill_metadata):
        """Test skill execution."""
        # Create actual skill file
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\nname: test-skill\n---\n# Test Skill\n\nContent here.",
            encoding="utf-8",
        )

        # Update metadata with correct path
        from backend.skills.discovery import SkillMetadata

        metadata = SkillMetadata(
            name="test-skill",
            description="A test skill",
            version="1.0.0",
            author="Test Author",
            tags=["test"],
            path=str(skill_md),
            skill_dir=str(skill_dir),
            triggers=["test"],
        )

        skill = DiscoveredSkill(metadata)
        result = skill.execute({}, {})

        assert result.success
        assert "Test Skill" in result.content
        assert result.metadata["skill_name"] == "test-skill"

    def test_execute_file_not_found(self, discovered_skill):
        """Test execution with missing file."""
        result = discovered_skill.execute({}, {})
        assert not result.success
        assert result.error is not None
