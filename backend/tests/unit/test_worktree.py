"""worktree 隔离基础函数测试 —— 真实 git 子进程 + tmp 目录。"""

import os
import subprocess
from pathlib import Path

import pytest

from backend.orchestration.worktree import (
    create_worktree,
    create_worktree_async,
    is_git_repo,
    remove_worktree,
)

pytestmark = pytest.mark.unit


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "init",
        ],
        check=True,
    )


def test_is_git_repo_true_and_false(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    assert is_git_repo(repo) is True
    plain = tmp_path / "plain"
    plain.mkdir()
    assert is_git_repo(plain) is False


def test_create_and_remove_worktree(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    dest = tmp_path / "wt"
    assert create_worktree(repo, dest) is True
    assert (dest / ".git").exists()
    remove_worktree(dest)
    assert not dest.exists()


def test_create_worktree_makes_missing_parent_dirs(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    dest = tmp_path / "a" / "b" / "c" / "wt"
    assert create_worktree(repo, dest) is True
    assert (dest / ".git").exists()
    remove_worktree(dest)
    assert not dest.exists()


def test_create_worktree_on_non_repo_returns_false(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert create_worktree(plain, tmp_path / "wt") is False


def test_create_worktree_fail_return_false_and_leave_no_dir(tmp_path):
    """git 命令失败（非空 repo → 冲突）→ False，不产生残留目录。"""
    repo = tmp_path / "repo"
    _init_repo(repo)
    dest = tmp_path / "wt"
    (tmp_path / "mark").write_text("occupied")
    (dest).mkdir(parents=True)
    assert create_worktree(repo, dest) is False


def test_timeout_returns_false(monkeypatch, tmp_path):
    """git 超时 → False，不抛异常。"""
    monkeypatch.setattr(
        "backend.orchestration.worktree._GIT_TIMEOUT_S", 0.2
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "git"
    script.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(10)\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    assert is_git_repo(tmp_path) is False


@pytest.mark.asyncio()
async def test_async_wrappers_delegate_to_thread(tmp_path):
    """异步包装经 executor 运行同步函数；create/cleanup 可用。"""
    from backend.orchestration.worktree import remove_worktree_async

    repo = tmp_path / "repo"
    _init_repo(repo)
    dest = tmp_path / "wt"
    assert await create_worktree_async(repo, dest) is True
    assert (dest / ".git").exists()
    await remove_worktree_async(dest)
    assert not dest.exists()
