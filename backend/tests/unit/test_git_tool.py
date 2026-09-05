"""git 工具组单元测试（对标增强 Phase-1 T1）。

用真实临时 git 仓库验证（git 命令跨平台可用，不依赖 POSIX 进程组，
Windows / CI 全绿）。覆盖：status/diff/log/commit 正常流 + 非仓库 +
未绑定工作区 + 路径越界 + 参数校验 + git 不可用降级。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools import git_tool
from backend.tools.git_tool import (
    GitCommitTool,
    GitDiffTool,
    GitLogTool,
    GitStatusTool,
)

pytestmark = [pytest.mark.unit]


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """带首次提交的最小 git 仓库（hello.txt + other.txt 均已跟踪）。"""
    _git("init", cwd=tmp_path)
    _git("config", "user.name", "Sage Test", cwd=tmp_path)
    _git("config", "user.email", "sage@example.com", cwd=tmp_path)
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    (tmp_path / "other.txt").write_text("base\n", encoding="utf-8")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-m", "init", cwd=tmp_path)
    return tmp_path


def _tool(tool_cls, root):
    return tool_cls(policy=ToolPolicy(workspace_root=str(root)))


# ---------------------------------------------------------------------------
# git_status
# ---------------------------------------------------------------------------


def test_status_clean_repo(repo):
    result = _tool(GitStatusTool, repo).execute()
    assert result.success is True
    assert result.content["clean"] is True
    assert result.content["branch"]
    assert result.content["changes"] == []


def test_status_lists_untracked_and_modified(repo):
    (repo / "hello.txt").write_text("changed\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")

    result = _tool(GitStatusTool, repo).execute()
    assert result.success is True
    assert result.content["clean"] is False
    by_path = {entry["path"]: entry for entry in result.content["changes"]}
    assert by_path["hello.txt"]["worktree_status"] == "M"
    assert by_path["new.txt"]["index_status"] == "?"
    assert by_path["new.txt"]["worktree_status"] == "?"


# ---------------------------------------------------------------------------
# git_diff
# ---------------------------------------------------------------------------


def test_diff_shows_modification(repo):
    (repo / "hello.txt").write_text("changed\n", encoding="utf-8")
    result = _tool(GitDiffTool, repo).execute()
    assert result.success is True
    assert "-hello" in result.content["diff"]
    assert "+changed" in result.content["diff"]
    assert result.content["truncated"] is False


def test_diff_staged_and_path_filter(repo):
    # git diff 不含未跟踪文件 —— other.txt 在 fixture 中已跟踪，这里改它
    (repo / "hello.txt").write_text("staged-change\n", encoding="utf-8")
    (repo / "other.txt").write_text("changed\n", encoding="utf-8")
    _git("add", "hello.txt", cwd=repo)

    tool = _tool(GitDiffTool, repo)
    staged = tool.execute(staged=True)
    assert staged.success is True
    assert "+staged-change" in staged.content["diff"]
    assert "other.txt" not in staged.content["diff"]

    scoped = tool.execute(path="other.txt")
    assert scoped.success is True
    assert "+changed" in scoped.content["diff"]
    assert "hello.txt" not in scoped.content["diff"]


def test_diff_rejects_path_outside_workspace(repo):
    result = _tool(GitDiffTool, repo).execute(path="../escape.txt")
    assert result.success is False
    assert "path_outside_workspace" in (result.error or "")


# ---------------------------------------------------------------------------
# git_log
# ---------------------------------------------------------------------------


def test_log_lists_commits(repo):
    (repo / "second.txt").write_text("2\n", encoding="utf-8")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "second", cwd=repo)

    result = _tool(GitLogTool, repo).execute()
    assert result.success is True
    subjects = [c["subject"] for c in result.content["commits"]]
    assert subjects == ["second", "init"]
    first = result.content["commits"][0]
    assert len(first["hash"]) == 40
    assert first["author"] == "Sage Test"
    assert first["date"]


def test_log_limit_and_validation(repo):
    tool = _tool(GitLogTool, repo)
    limited = tool.execute(limit=1)
    assert limited.success is True
    assert len(limited.content["commits"]) == 1

    assert tool.execute(limit=0).success is False
    assert tool.execute(limit="3").success is False


def test_log_path_scoping(repo):
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "add a", cwd=repo)

    result = _tool(GitLogTool, repo).execute(path="hello.txt")
    assert result.success is True
    assert [c["subject"] for c in result.content["commits"]] == ["init"]


# ---------------------------------------------------------------------------
# git_commit
# ---------------------------------------------------------------------------


def test_commit_with_add_all(repo):
    (repo / "feature.txt").write_text("feat\n", encoding="utf-8")
    result = _tool(GitCommitTool, repo).execute(
        message="feat: add feature", add_all=True
    )
    assert result.success is True
    assert len(result.content["commit_hash"]) == 40

    status = _tool(GitStatusTool, repo).execute()
    assert status.content["clean"] is True
    log = _tool(GitLogTool, repo).execute(limit=1)
    assert log.content["commits"][0]["subject"] == "feat: add feature"


def test_commit_with_explicit_paths(repo):
    (repo / "keep.txt").write_text("keep\n", encoding="utf-8")
    (repo / "skip.txt").write_text("skip\n", encoding="utf-8")
    result = _tool(GitCommitTool, repo).execute(
        message="only keep", paths=["keep.txt"]
    )
    assert result.success is True
    status = _tool(GitStatusTool, repo).execute()
    remaining = {entry["path"] for entry in status.content["changes"]}
    assert remaining == {"skip.txt"}


def test_commit_nothing_to_commit_fails_gracefully(repo):
    result = _tool(GitCommitTool, repo).execute(message="empty")
    assert result.success is False
    assert "nothing" in (result.error or "").lower()


def test_commit_validation(repo):
    tool = _tool(GitCommitTool, repo)
    assert tool.execute(message="").success is False
    assert tool.execute(message="x", paths=["../escape.txt"]).success is False
    assert tool.execute(message="x", paths=[42]).success is False
    assert tool.execute(message="x", unknown_param=1).success is False


# ---------------------------------------------------------------------------
# 环境边界
# ---------------------------------------------------------------------------


def test_requires_bound_workspace():
    for tool_cls in (GitStatusTool, GitDiffTool, GitLogTool, GitCommitTool):
        result = tool_cls(policy=ToolPolicy()).execute()
        assert result.success is False
        assert "绑定工作区" in (result.error or "")


def test_non_repo_directory_fails_gracefully(tmp_path):
    result = _tool(GitStatusTool, tmp_path).execute()
    assert result.success is False
    assert "not a git repository" in (result.error or "")


def test_git_binary_missing_fails_gracefully(repo, monkeypatch):
    monkeypatch.setattr(git_tool, "GIT_BINARY", "definitely-not-git-xyz")
    result = _tool(GitStatusTool, repo).execute()
    assert result.success is False
    assert "git 可执行文件不可用" in (result.error or "")
