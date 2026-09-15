"""Authorization helpers for registered Wiki project roots."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List

from fastapi import HTTPException

from backend.storage.recent_projects import load_recent

logger = logging.getLogger(__name__)


def _projects_registry_paths() -> List[Path]:
    """P6 桥接：projects 注册表（backend/data/project_repo.py）中的路径。

    用户在侧边栏"项目"里显式登记的工作目录与 wiki recents 同一信任来源
    （"用户把该目录用作 Sage 的工作上下文"），因此授权判定取两者并集。

    Lazy import：保持本模块对 data 层零硬依赖，也便于测试 monkeypatch
    本函数。任何读取失败 → 空列表（fail-closed，与 recents 同语义）。
    """
    try:
        from backend.data.project_repo import ProjectRepository

        return [Path(item.path) for item in ProjectRepository().list(limit=200)]
    except Exception as exc:  # noqa: BLE001 — 读取失败绝不放宽授权
        logger.debug("projects registry unavailable for authorization: %s", exc)
        return []


def canonical_project_path(project_path: str) -> Path | None:
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

    # P6 桥接：projects 注册表命中同样视为已登记（recents ∪ registry）。
    # 与 recents 分支同款 try/except —— 任何异常一律视为未登记（fail-closed）。
    if not registered:
        try:
            for item_path in _projects_registry_paths():
                resolved = canonical_project_path(str(item_path))
                if resolved is not None and _same_path(resolved, canonical):
                    registered = True
                    break
        except Exception:
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
