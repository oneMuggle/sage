"""git_commit_message 工具单元测试（G9 提交素材）。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools.commit_message_tool import GitCommitMessageTool

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        os.name == "nt",
        reason="commit message 子进程在 Windows 的调用差异（另行批次定性）",
    ),
]


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _git("init", cwd=tmp_path)
    _git("config", "user.name", "Sage Test", cwd=tmp_path)
    _git("config", "user.email", "sage@example.com", cwd=tmp_path)
    (tmp_path / "hello.txt").write_text("hello\n", encoding="utf-8")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-m", "init: hello", cwd=tmp_path)
    return tmp_path


def _tool(root: Path) -> GitCommitMessageTool:
    return GitCommitMessageTool(policy=ToolPolicy(workspace_root=str(root)))


def test_summarizes_staged_changes_with_style(repo):
    (repo / "hello.txt").write_text("hello world\n", encoding="utf-8")
    (repo / "new.py").write_text("x = 1\n", encoding="utf-8")
    _git("add", ".", cwd=repo)

    result = _tool(repo).execute()
    assert result.success is True
    content = result.content
    assert content["file_count"] == 2
    paths = {f["path"] for f in content["files"]}
    assert paths == {"hello.txt", "new.py"}
    assert "+hello world" in content["diff"]
    assert content["diff_truncated"] is False
    assert content["recent_subjects"] == ["init: hello"]
    assert "git_commit" in content["hint"]


def test_empty_staging_area_fails_gracefully(repo):
    result = _tool(repo).execute()
    assert result.success is False
    assert "暂存区为空" in (result.error or "")


def test_non_repo_and_unbound_fail(repo, tmp_path):
    result = GitCommitMessageTool(
        policy=ToolPolicy(workspace_root=str(tmp_path / "nope"))
    ).execute()
    assert result.success is False

    result = GitCommitMessageTool(policy=ToolPolicy()).execute()
    assert result.success is False
    assert "绑定工作区" in (result.error or "")


def test_accepts_no_params(repo):
    result = _tool(repo).execute(bogus=1)
    assert result.success is False
