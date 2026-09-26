"""
Skill discovery service.

This module provides the SkillDiscoveryService for automatically discovering
skills from the local filesystem (~/.sage/skills/).

It scans for SKILL.md files, parses their metadata, and registers them
with the skill registry.

Author: Claude
Date: 2026-09-26
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SkillMetadata(BaseModel):
    """Metadata extracted from a SKILL.md file."""

    name: str = Field(..., description="技能名称")
    description: str = Field(default="", description="技能描述")
    version: str = Field(default="1.0.0", description="技能版本")
    author: str = Field(default="", description="作者")
    tags: List[str] = Field(default_factory=list, description="标签")
    path: str = Field(..., description="SKILL.md 文件路径")
    skill_dir: str = Field(..., description="技能目录路径")

    # Frontmatter 字段
    triggers: List[str] = Field(default_factory=list, description="触发条件")
    allowed_tools: List[str] = Field(default_factory=list, description="允许的工具")
    priority: int = Field(default=0, description="优先级")


class SkillDiscoveryError(Exception):
    """Base exception for skill discovery errors."""

    pass


class SkillNotFoundError(SkillDiscoveryError):
    """Raised when skill is not found."""

    pass


class SkillDiscoveryService:
    """
    Discover skills from the local filesystem.

    Scans ~/.sage/skills/ (or custom directory) for SKILL.md files,
    parses their metadata, and provides discovery results.

    Usage:
        service = SkillDiscoveryService()
        skills = service.discover_all()
        metadata = service.discover_one("my-skill")
    """

    def __init__(self, skills_dir: Optional[Path | str] = None) -> None:
        """
        Initialize discovery service.

        Args:
            skills_dir: Custom skills directory. If None, uses default.
        """
        if skills_dir is not None:
            self._skills_dir = Path(skills_dir)
        else:
            # Default: ~/.sage/skills
            self._skills_dir = self._get_default_skills_dir()

        # Cache for discovered skills
        self._cache: dict[str, SkillMetadata] = {}
        self._cache_valid = False

    def _get_default_skills_dir(self) -> Path:
        """Get default skills directory."""
        # Check environment variable first
        env_dir = os.environ.get("SAGE_SKILLS_DIR")
        if env_dir:
            return Path(env_dir)

        # Default to ~/.sage/skills
        return Path.home() / ".sage" / "skills"

    @property
    def skills_dir(self) -> Path:
        """Get the skills directory."""
        return self._skills_dir

    def discover_all(self, use_cache: bool = True) -> list[SkillMetadata]:
        """
        Discover all skills in the skills directory.

        Args:
            use_cache: Whether to use cached results

        Returns:
            List of SkillMetadata
        """
        if use_cache and self._cache_valid:
            return list(self._cache.values())

        if not self._skills_dir.exists():
            logger.warning(f"技能目录不存在: {self._skills_dir}")
            return []

        if not self._skills_dir.is_dir():
            logger.error(f"技能路径不是目录: {self._skills_dir}")
            return []

        discovered = []

        # Scan for SKILL.md files
        for skill_dir in self._skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                metadata = self._parse_skill_md(skill_md)
                discovered.append(metadata)
                self._cache[metadata.name] = metadata
            except Exception as e:
                logger.error(f"解析技能失败 {skill_md}: {e}")

        self._cache_valid = True

        logger.info(f"发现 {len(discovered)} 个技能")

        return discovered

    def discover_one(self, skill_name: str) -> SkillMetadata:
        """
        Discover a specific skill by name.

        Args:
            skill_name: Skill name

        Returns:
            SkillMetadata

        Raises:
            SkillNotFoundError: If skill not found
        """
        # Check cache first
        if skill_name in self._cache:
            return self._cache[skill_name]

        skill_dir = self._skills_dir / skill_name
        skill_md = skill_dir / "SKILL.md"

        if not skill_md.exists():
            raise SkillNotFoundError(f"技能未找到: {skill_name}")

        metadata = self._parse_skill_md(skill_md)
        self._cache[skill_name] = metadata

        return metadata

    def _parse_skill_md(self, skill_md_path: Path) -> SkillMetadata:
        """
        Parse a SKILL.md file and extract metadata.

        Args:
            skill_md_path: Path to SKILL.md file

        Returns:
            SkillMetadata
        """
        content = skill_md_path.read_text(encoding="utf-8")

        # Extract frontmatter
        frontmatter = self._extract_frontmatter(content)

        # Extract name from directory name
        skill_dir = skill_md_path.parent
        skill_name = frontmatter.get("name", skill_dir.name)

        # Extract description from first paragraph or frontmatter
        description = frontmatter.get("description", "")
        if not description:
            description = self._extract_first_paragraph(content)

        # Parse tags
        tags = frontmatter.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]

        # Parse triggers
        triggers = frontmatter.get("triggers", [])
        if isinstance(triggers, str):
            triggers = [t.strip() for t in triggers.split(",")]

        # Parse allowed-tools
        allowed_tools = frontmatter.get("allowed-tools", [])
        if isinstance(allowed_tools, str):
            allowed_tools = [t.strip() for t in allowed_tools.split(",")]

        return SkillMetadata(
            name=skill_name,
            description=description,
            version=frontmatter.get("version", "1.0.0"),
            author=frontmatter.get("author", ""),
            tags=tags,
            path=str(skill_md_path),
            skill_dir=str(skill_dir),
            triggers=triggers,
            allowed_tools=allowed_tools,
            priority=int(frontmatter.get("priority", 0)),
        )

    def _extract_frontmatter(self, content: str) -> dict[str, Any]:
        """
        Extract YAML frontmatter from SKILL.md content.

        Args:
            content: SKILL.md content

        Returns:
            Dictionary of frontmatter fields
        """
        # Look for --- delimited frontmatter
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not match:
            return {}

        frontmatter_text = match.group(1)
        result = {}

        # Simple YAML parsing (key: value pairs)
        for raw_line in frontmatter_text.split("\n"):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            # Parse key: value
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()

                # Parse lists (comma-separated or YAML array)
                if value.startswith("[") and value.endswith("]"):
                    # Inline array: [a, b, c]
                    items = value[1:-1].split(",")
                    value = [item.strip().strip('"').strip("'") for item in items]
                elif value.startswith("-"):
                    # Multi-line array (not fully parsed here)
                    value = [value[1:].strip()]
                else:
                    # Remove quotes
                    value = value.strip('"').strip("'")

                result[key] = value

        return result

    def _extract_first_paragraph(self, content: str) -> str:
        """
        Extract the first paragraph from SKILL.md content.

        Args:
            content: SKILL.md content

        Returns:
            First paragraph text
        """
        # Remove frontmatter
        content = re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, flags=re.DOTALL)

        # Remove leading whitespace and markdown headers
        lines = content.split("\n")
        paragraph_lines = []

        for raw_line in lines:
            line = raw_line.strip()

            # Skip empty lines at start
            if not paragraph_lines and not line:
                continue

            # Skip headers
            if line.startswith("#"):
                continue

            # Collect paragraph
            if line:
                paragraph_lines.append(line)
            elif paragraph_lines:
                # End of paragraph
                break

        return " ".join(paragraph_lines)

    def invalidate_cache(self) -> None:
        """Invalidate the discovery cache."""
        self._cache.clear()
        self._cache_valid = False
        logger.debug("技能发现缓存已失效")

    def list_skill_names(self) -> list[str]:
        """
        List all discovered skill names.

        Returns:
            List of skill names
        """
        skills = self.discover_all()
        return [skill.name for skill in skills]

    def has_skill(self, skill_name: str) -> bool:
        """
        Check if a skill exists.

        Args:
            skill_name: Skill name

        Returns:
            True if skill exists
        """
        skill_dir = self._skills_dir / skill_name
        skill_md = skill_dir / "SKILL.md"
        return skill_md.exists()

    def get_skill_content(self, skill_name: str) -> str:
        """
        Get the full content of a SKILL.md file.

        Args:
            skill_name: Skill name

        Returns:
            SKILL.md content

        Raises:
            SkillNotFoundError: If skill not found
        """
        skill_dir = self._skills_dir / skill_name
        skill_md = skill_dir / "SKILL.md"

        if not skill_md.exists():
            raise SkillNotFoundError(f"技能未找到: {skill_name}")

        return skill_md.read_text(encoding="utf-8")


# Global instance
_discovery_service: Optional[SkillDiscoveryService] = None


def get_skill_discovery_service() -> SkillDiscoveryService:
    """Get global skill discovery service instance."""
    global _discovery_service
    if _discovery_service is None:
        _discovery_service = SkillDiscoveryService()
    return _discovery_service
