"""worktree 隔离基础函数测试 —— 真实 git 子进程 + tmp 目录。"""

import subprocess
from pathlib import Path

import pytest

from backend.orchestration.worktree import create_worktree, is_git_repo, remove_worktree

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


def test_create_worktree_on_non_repo_returns_false(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert create_worktree(plain, tmp_path / "wt") is False
