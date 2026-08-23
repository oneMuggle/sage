"""Git worktree 隔离 —— 编排子任务的可选文件系统隔离层（P2）。

开启 ``orch.worktreeIsolation`` 且会话绑定 git 仓库工作区时，每个子任务在
workspace 的临时 detached worktree 副本中工作。副本只提供隔离，不自动合并
产物回主工作区；调用方在任务结束后负责清理。

所有 git 调用均有超时保护；任何失败都静默降级为 False 或 no-op，由调用方
回落到既有 scratch 目录隔离。
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_GIT_TIMEOUT_S = 30


def _run_git(args: List[str], cwd: Optional[Path] = None) -> bool:
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("git %s 失败: %s", args[:2], exc)
        return False


def is_git_repo(path: Path) -> bool:
    """Return whether ``path`` is an existing directory inside a git work tree."""
    return path.is_dir() and _run_git(
        ["rev-parse", "--is-inside-work-tree"], cwd=path
    )


def create_worktree(repo: Path, dest: Path) -> bool:
    """从 ``repo`` 的 HEAD 建 detached worktree 到 ``dest``。失败返回 False。"""
    if not is_git_repo(repo) or dest.exists():
        return False
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        ok = _run_git(
            ["worktree", "add", "--detach", str(dest), "HEAD"],
            cwd=repo,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("worktree 创建异常 repo=%s dest=%s: %s", repo, dest, exc)
        return False
    if not ok:
        logger.warning("worktree 创建失败 repo=%s dest=%s", repo, dest)
    return ok


def remove_worktree(dest: Path) -> None:
    """强制移除 worktree（含未提交变更）；dest 不存在则 no-op。"""
    if not dest.exists():
        return
    try:
        prune_ok = _run_git(["worktree", "prune"], cwd=dest)
        if not prune_ok:
            logger.debug("worktree prune 失败: %s", dest)
        if not _run_git(["worktree", "remove", "--force", str(dest)], cwd=dest):
            logger.warning("worktree 移除失败（将遗留目录）: %s", dest)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("worktree 移除异常（将遗留目录）: %s: %s", dest, exc)


async def create_worktree_async(repo: Path, dest: Path) -> bool:
    """在线程中创建 worktree，避免阻塞 asyncio event loop。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, create_worktree, repo, dest)


async def remove_worktree_async(dest: Path) -> None:
    """在线程中清理 worktree；异常仅记录，不向任务传播。"""
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, remove_worktree, dest)
    except Exception as exc:  # noqa: BLE001 — 清理不得覆盖任务结果
        logger.warning("worktree 异步清理异常（忽略）: %s: %s", dest, exc)


async def is_git_repo_async(path: Path) -> bool:
    """在线程中判断 git repo，避免阻塞 asyncio event loop。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, is_git_repo, path)
