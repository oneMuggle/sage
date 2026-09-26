"""
Enhanced skill registry with discovery integration.

This module provides an enhanced skill registry that integrates with
SkillDiscoveryService for automatic skill discovery and registration.

Author: Claude
Date: 2026-09-26
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.skills.base import BaseSkill, SkillResult
from backend.skills.discovery import SkillDiscoveryService, SkillMetadata
from backend.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class EnhancedSkillRegistry(SkillRegistry):
    """
    Enhanced skill registry with discovery integration.

    Extends SkillRegistry to support:
    - Automatic skill discovery from filesystem
    - Skill metadata management
    - Integration with plugin capability registry

    Usage:
        registry = EnhancedSkillRegistry()
        registry.discover_and_register()
        skills = registry.list_with_metadata()
    """

    def __init__(
        self,
        discovery_service: Optional[SkillDiscoveryService] = None,
    ) -> None:
        """
        Initialize enhanced registry.

        Args:
            discovery_service: Optional discovery service. If None, uses default.
        """
        super().__init__()
        self._discovery_service = discovery_service
        self._metadata_cache: dict[str, SkillMetadata] = {}

    @property
    def discovery_service(self) -> SkillDiscoveryService:
        """Get discovery service (lazy initialization)."""
        if self._discovery_service is None:
            self._discovery_service = SkillDiscoveryService()
        return self._discovery_service

    def discover_and_register(self) -> int:
        """
        Discover skills from filesystem and register them.

        Returns:
            Number of newly registered skills
        """
        discovered = self.discovery_service.discover_all()
        registered_count = 0

        for metadata in discovered:
            # Skip if already registered
            if self.exists(metadata.name):
                continue

            # Create a wrapper skill from metadata
            skill = DiscoveredSkill(metadata)
            self.register(skill)
            self._metadata_cache[metadata.name] = metadata
            registered_count += 1

            logger.info(f"已注册发现的技能: {metadata.name}")

        logger.info(f"发现并注册了 {registered_count} 个技能")
        return registered_count

    def register_with_metadata(
        self, skill: BaseSkill, metadata: Optional[SkillMetadata] = None
    ) -> None:
        """
        Register a skill with optional metadata.

        Args:
            skill: Skill instance
            metadata: Optional skill metadata
        """
        self.register(skill)

        if metadata is not None:
            self._metadata_cache[skill.name] = metadata

    def get_metadata(self, skill_name: str) -> Optional[SkillMetadata]:
        """
        Get metadata for a skill.

        Args:
            skill_name: Skill name

        Returns:
            SkillMetadata or None
        """
        return self._metadata_cache.get(skill_name)

    def list_with_metadata(self) -> list[tuple[BaseSkill, Optional[SkillMetadata]]]:
        """
        List all skills with their metadata.

        Returns:
            List of (skill, metadata) tuples
        """
        result = []
        for skill in self._skills.values():
            metadata = self._metadata_cache.get(skill.name)
            result.append((skill, metadata))
        return result

    def refresh_discovery(self) -> int:
        """
        Refresh discovery and register new skills.

        Returns:
            Number of newly registered skills
        """
        self.discovery_service.invalidate_cache()
        return self.discover_and_register()


class DiscoveredSkill(BaseSkill):
    """
    Wrapper for discovered skills from SKILL.md files.

    This allows discovered skills to be used like regular skills
    in the registry.
    """

    def __init__(self, metadata: SkillMetadata) -> None:
        """
        Initialize discovered skill.

        Args:
            metadata: Skill metadata from discovery
        """
        super().__init__()
        self._metadata = metadata

    def _build_schema(self) -> "SkillSchema":
        """
        Build skill schema from metadata.

        Returns:
            SkillSchema
        """
        from backend.skills.base import SkillSchema

        return SkillSchema(
            name=self._metadata.name,
            description=self._metadata.description,
            triggers=self._metadata.triggers or [],
            parameters={},  # Discovered skills don't have structured parameters
            examples=[],
        )

    def match(self, text: str) -> bool:
        """
        Check if this skill matches the input text.

        Args:
            text: User input text

        Returns:
            True if matches
        """
        # Match against triggers
        text_lower = text.lower()
        for trigger in self._metadata.triggers:
            if trigger.lower() in text_lower:
                return True

        # Match against skill name
        if self.name.lower() in text_lower:
            return True

        return False

    def execute(self, params: dict, context: dict) -> SkillResult:
        """
        Execute the skill.

        For discovered skills, this returns the SKILL.md content
        as the skill output.

        Args:
            params: Skill parameters
            context: Execution context

        Returns:
            SkillResult
        """
        try:
            # Read content directly from stored path
            from pathlib import Path

            skill_md_path = Path(self._metadata.path)
            content = skill_md_path.read_text(encoding="utf-8")

            return SkillResult(
                success=True,
                content=content,
                metadata={
                    "skill_name": self.name,
                    "skill_path": self._metadata.path,
                    "skill_dir": self._metadata.skill_dir,
                },
            )
        except Exception as e:
            logger.error(f"技能执行失败: {self.name}, error: {e}")
            return SkillResult(
                success=False,
                error=f"技能执行失败: {str(e)}",
            )


# Global instance
_enhanced_registry: Optional[EnhancedSkillRegistry] = None


def get_enhanced_skill_registry() -> EnhancedSkillRegistry:
    """Get global enhanced skill registry instance."""
    global _enhanced_registry
    if _enhanced_registry is None:
        _enhanced_registry = EnhancedSkillRegistry()
    return _enhanced_registry


if __name__ == "__main__":
    # Test enhanced registry
    import tempfile
    from pathlib import Path

    print("Testing EnhancedSkillRegistry...")

    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)

        # Create test skill
        skill_dir = skills_dir / "test-skill"
        skill_dir.mkdir()

        skill_content = """---
name: test-skill
description: A test skill
version: 1.0.0
author: Test Author
tags: test, demo
triggers: test, example
---

# Test Skill

This is the content of the test skill.
"""

        (skill_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")

        # Create discovery service
        discovery = SkillDiscoveryService(skills_dir=skills_dir)

        # Create enhanced registry
        registry = EnhancedSkillRegistry(discovery_service=discovery)

        print("\n1. Testing discover_and_register...")
        count = registry.discover_and_register()
        assert count == 1
        print(f"✅ Discovered and registered: {count} skill(s)")

        print("\n2. Testing get_metadata...")
        metadata = registry.get_metadata("test-skill")
        assert metadata is not None
        assert metadata.name == "test-skill"
        print(f"✅ Got metadata: {metadata.name} v{metadata.version}")

        print("\n3. Testing list_with_metadata...")
        skills_with_meta = registry.list_with_metadata()
        assert len(skills_with_meta) == 1
        skill, meta = skills_with_meta[0]
        assert skill.name == "test-skill"
        assert meta is not None
        print(f"✅ Listed with metadata: {len(skills_with_meta)} skill(s)")

        print("\n4. Testing skill matching...")
        skill = registry.get("test-skill")
        assert skill is not None
        assert skill.match("this is a test")
        print("✅ Skill matching works")

        print("\n5. Testing skill execution...")
        result = skill.execute({}, {})
        assert result.success
        assert "Test Skill" in result.content
        print(f"✅ Skill executed, output: {len(result.content)} chars")

    print("\n✅ All enhanced registry tests passed!")
