"""Project Git initialization (2026-10-29).

Only used when the user explicitly accepts the "enable Git tracking"
suggestion during AI bootstrap. Read-only Git operations stay in
``git_integration.py``; this module is the single write-side entry point
and never runs when ``git`` is unavailable (Win7 without PortableGit).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

GIT_TIMEOUT_SECONDS = 30.0


def git_available() -> bool:
    """Return True when a ``git`` executable is on PATH."""
    return shutil.which("git") is not None


def init_project_git(root: str) -> Dict[str, Any]:
    """Run ``git init`` in the project root.

    Returns a dict with:
      - initialized: bool (True only when this call created the repo)
      - already_repo: bool (``.git`` already existed)
      - git_available: bool
      - error: Optional[str]
    """
    root_path = Path(root)
    available = git_available()
    if (root_path / ".git").exists():
        return {
            "initialized": False,
            "already_repo": True,
            "git_available": available,
            "error": None,
        }
    if not available:
        return {
            "initialized": False,
            "already_repo": False,
            "git_available": False,
            "error": "git_not_available",
        }

    try:
        completed = subprocess.run(
            ["git", "init"],
            cwd=str(root_path),
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("git init failed for %s: %s", root_path, exc)
        return {
            "initialized": False,
            "already_repo": False,
            "git_available": True,
            "error": str(exc),
        }

    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip() or (
            "git init failed"
        )
        logger.warning("git init returned %s for %s: %s", completed.returncode, root_path, detail)
        return {
            "initialized": False,
            "already_repo": False,
            "git_available": True,
            "error": detail,
        }

    return {
        "initialized": True,
        "already_repo": False,
        "git_available": True,
        "error": None,
    }
