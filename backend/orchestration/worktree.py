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


def _run_git_out(args: List[str], cwd: Optional[Path] = None) -> Optional[str]:
    """执行 git 子命令并返回 stdout；失败（非 0 退出 / 异常）返回 None。"""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("git %s 失败: %s", args[:2], exc)
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", errors="replace")


def is_git_repo(path: Path) -> bool:
    """Return whether ``path`` is an existing directory inside a git work tree."""
    return path.is_dir() and _run_git(
        ["rev-parse", "--is-inside-work-tree"], cwd=path
    )


def create_worktree(
    repo: Path,
    dest: Path,
    branch: Optional[str] = None,
    base_ref: str = "HEAD",
    create_branch: bool = True,
) -> bool:
    """从 ``repo`` 建 worktree 到 ``dest``。失败返回 False。

    ``branch`` 为空时保持旧行为：HEAD 的 detached 副本（编排 lane 隔离用）。
    ``create_branch=True`` 时 ``git worktree add -b <branch> <dest> <base_ref>``；
    ``create_branch=False`` 时检出已有分支 ``git worktree add <dest> <branch>``。
    分支名过 :func:`backend.tools.git_tool._valid_ref` 白名单防注入。
    """
    if not is_git_repo(repo) or dest.exists():
        return False
    if branch is not None:
        from backend.tools.git_tool import _valid_ref

        if not _valid_ref(branch) or (create_branch and not _valid_ref(base_ref)):
            logger.warning("worktree 分支名非法: branch=%r base=%r", branch, base_ref)
            return False
        if create_branch:
            add_args = ["worktree", "add", "-b", branch, str(dest), base_ref]
        else:
            add_args = ["worktree", "add", str(dest), branch]
    else:
        add_args = ["worktree", "add", "--detach", str(dest), "HEAD"]
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        ok = _run_git(add_args, cwd=repo)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("worktree 创建异常 repo=%s dest=%s: %s", repo, dest, exc)
        return False
    if not ok:
        logger.warning("worktree 创建失败 repo=%s dest=%s branch=%s", repo, dest, branch)
    return ok


def list_worktrees(repo: Path) -> List[dict]:
    """``git worktree list --porcelain`` 解析结果。

    每项: ``{path, head, branch, detached, main}``；``branch`` 为裸分支名
    （detached 时为 None），``main`` 标记主仓（porcelain 输出首条）。
    失败返回空列表。
    """
    out = _run_git_out(["worktree", "list", "--porcelain"], cwd=repo)
    if out is None:
        return []
    entries: List[dict] = []
    current: Optional[dict] = None
    for line in out.splitlines():
        line = line.rstrip()
        if line.startswith("worktree "):
            if current is not None:
                entries.append(current)
            raw_path = line[len("worktree "):]
            current = {
                "path": raw_path,
                "head": "",
                "branch": None,
                "detached": False,
                "main": not entries,
            }
        elif current is None:
            continue
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):]
        elif line == "detached":
            current["detached"] = True
        elif line.startswith("branch "):
            ref = line[len("branch "):]
            prefix = "refs/heads/"
            if ref.startswith(prefix):
                ref = ref[len(prefix):]
            current["branch"] = ref
    if current is not None:
        entries.append(current)
    return entries


def remove_worktree(dest: Path) -> None:
    """强制移除 worktree（含未提交变更）；dest 不存在则 no-op。"""
    if not dest.exists():
        return
    try:
        prune_ok = _run_git(["worktree", "prune"], cwd=dest)
        if not prune_ok:
            logger.debug("worktree prune 失败: %s", dest)
        # remove 的 cwd 必须「在同一 repo 内、但不在 dest 自身内」：
        # cwd=dest 在 Windows 上删目录会 Permission denied（进程锁 cwd），
        # cwd 在 repo 外则 git 报 not a git repository。经主仓执行最稳。
        from backend.orchestration.worktree_merge import find_main_repo

        main = find_main_repo(dest)
        if not _run_git(
            ["worktree", "remove", "--force", str(dest)],
            cwd=main if main is not None else dest.parent,
        ):
            logger.warning("worktree 移除失败（将遗留目录）: %s", dest)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("worktree 移除异常（将遗留目录）: %s: %s", dest, exc)


def prune_worktrees(cwd: Optional[Path] = None) -> bool:
    """在 ``cwd`` 上执行 ``git worktree prune``，清掉悬空的 worktree 管理元数据。

    场景（安全修复波 2026-08-23）：崩溃残留的 worktree 目录被直接 rmtree 后，
    主仓 ``.git/worktrees/`` 条目仍在 —— 同路径重建 ``git worktree add`` 会
    rc=128 失败并静默回落 scratch。prune 清掉这类孤儿条目。失败返回 False。
    """
    if cwd is not None and not cwd.is_dir():
        return False
    return _run_git(["worktree", "prune"], cwd=cwd)


async def create_worktree_async(
    repo: Path,
    dest: Path,
    branch: Optional[str] = None,
    base_ref: str = "HEAD",
) -> bool:
    """在线程中创建 worktree，避免阻塞 asyncio event loop。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, create_worktree, repo, dest, branch, base_ref
    )


async def list_worktrees_async(repo: Path) -> List[dict]:
    """在线程中列出 worktree，避免阻塞 asyncio event loop。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, list_worktrees, repo)


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
