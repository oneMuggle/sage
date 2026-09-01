"""Authorization helpers for registered Wiki project roots."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from backend.storage.recent_projects import load_recent


def canonical_project_path(project_path: str) -> Optional[Path]:
    """Return a canonical absolute path, or ``None`` for invalid input.

    The path supplied by the caller itself may not be a symlink. Resolution is
    non-strict so this helper can also be used by project creation/check flows.
    """
    if not project_path or "\x00" in project_path:
        return None
    try:
        declared = Path(project_path).expanduser()
        if not declared.is_absolute() or declared.is_symlink():
            return None
        return declared.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _valid_project_directory(path: Path) -> bool:
    try:
        return path.is_dir() and (path / "wiki").is_dir()
    except OSError:
        return False


def authorize_registered_project(project_path: str) -> Path:
    """Authorize access to a previously registered, still-existing Wiki root."""
    canonical = canonical_project_path(project_path)
    if canonical is None:
        raise HTTPException(status_code=400, detail="项目路径无效")

    registered = False
    try:
        for item in load_recent():
            item_path = canonical_project_path(item.path)
            if item_path is not None and _same_path(item_path, canonical):
                registered = True
                break
    except Exception:
        # A malformed/unreadable registry must never grant access.
        registered = False

    if not registered:
        raise HTTPException(status_code=403, detail="项目未授权")
    if not _valid_project_directory(canonical):
        raise HTTPException(status_code=404, detail="项目不存在")
    return canonical


def authorize_registration(path: str, intent: str) -> Path:
    """Validate a path before recording it as a recent project."""
    canonical = canonical_project_path(path)
    if canonical is None:
        raise HTTPException(status_code=400, detail="项目路径无效")
    if not _valid_project_directory(canonical):
        raise HTTPException(status_code=404, detail="项目不是有效的 Wiki 项目")
    return canonical
