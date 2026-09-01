"""SkillLoader — writes approved skill drafts to disk as SKILL.md.

This module provides a thin abstraction over the file-system layout
used by the SKILL.md ecosystem:

    <skills_dir>/<skill_name>/SKILL.md

The ``write()`` method creates the directory if needed and writes the
content.  It is intentionally minimal — it does *not* hot-reload the
skill into the running registry (that is the caller's responsibility,
e.g. via ``SkillMdHotLoader.hot_reload``).

Singleton access: ``get_skill_loader()``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from .safe_writer import write_skill_file

logger = logging.getLogger(__name__)


class SkillLoader:
    """Write approved skill drafts to disk as SKILL.md files.

    Args:
        skills_dir: Root directory under which skills are stored.
            Each skill becomes ``<skills_dir>/<name>/SKILL.md``.
            Defaults to ``$SAGE_SKILLS_DIR`` → ``~/.sage/skills``.
    """

    def __init__(self, skills_dir: Optional[Path] = None) -> None:
        self._explicit_skills_dir = skills_dir

    def write(self, name: str, content: str, *, overwrite: bool = True) -> Path:
        """Write a skill's content to ``<skills_dir>/<name>/SKILL.md``.

        Args:
            name: The skill name (used as the directory name).
                Must be a valid path component (no slashes, no ``..``).
            content: The full SKILL.md body (frontmatter + markdown).

        Returns:
            The path to the written file.

        Raises:
            ValueError: ``name`` is empty or contains path separators.
            OSError: File-system write failure (permission denied, etc.).
        """
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            raise ValueError(f"Invalid skill name: {name!r}")

        skills_dir = self._resolve_skills_dir()
        target_file = write_skill_file(skills_dir, name, content, overwrite=overwrite)

        logger.info("Skill written to %s", target_file)
        return target_file

    def _resolve_skills_dir(self) -> Path:
        """Resolve the skills directory.

        Priority:
          1. Explicit ``skills_dir`` passed to constructor
          2. ``$SAGE_SKILLS_DIR`` environment variable
          3. ``~/.sage/skills`` (default, created if missing)
        """
        if self._explicit_skills_dir is not None:
            d = self._explicit_skills_dir.expanduser()
            d.mkdir(parents=True, exist_ok=True)
            return d

        env = os.environ.get("SAGE_SKILLS_DIR", "").strip()
        if env:
            d = Path(env).expanduser()
            d.mkdir(parents=True, exist_ok=True)
            return d

        user_dir = Path.home() / ".sage" / "skills"
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir


# ------------------------------------------------------------------ #
# Global singleton
# ------------------------------------------------------------------ #

_skill_loader: Optional[SkillLoader] = None


def get_skill_loader() -> SkillLoader:
    """Return the global SkillLoader singleton."""
    global _skill_loader
    if _skill_loader is None:
        _skill_loader = SkillLoader()
    return _skill_loader


def reset_skill_loader() -> None:
    """Reset the global SkillLoader singleton (test only)."""
    global _skill_loader
    _skill_loader = None
