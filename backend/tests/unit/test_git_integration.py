"""GitIntegration 单元测试 (项目类型分类系统, 2026-09-24)。

覆盖:
- is_git_repo: 检测 git 仓库
- get_current_branch: 获取当前分支
- get_status: 获取仓库状态
- get_log: 获取提交记录
- get_diff: 获取变更 diff
- get_gitignore_patterns: 读取 .gitignore
- get_summary: 获取仓库摘要

使用真实的 git 命令在临时目录中创建测试仓库。
"""

from __future__ import annotations

import subprocess

import pytest

from backend.services.git_integration import GitIntegration

pytestmark = [pytest.mark.unit]


@pytest.fixture()
def git_repo(tmp_path):
    """创建一个有提交记录的临时 git 仓库。"""
    repo_path = tmp_path / "test-repo"
    repo_path.mkdir()

    # 初始化 git 仓库
    subprocess.run(["git", "init"], cwd=str(repo_path), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(repo_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(repo_path),
        check=True,
        capture_output=True,
    )

    # 创建初始提交
    (repo_path / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=str(repo_path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(repo_path),
        check=True,
        capture_output=True,
    )

    return repo_path


class TestIsGitRepo:
    """is_git_repo: 检测 git 仓库。"""

    def test_git_repo_returns_true(self, git_repo):
        """git 仓库返回 True。"""
        git = GitIntegration(str(git_repo))
        assert git.is_git_repo() is True

    def test_non_repo_returns_false(self, tmp_path):
        """非 git 目录返回 False。"""
        git = GitIntegration(str(tmp_path))
        assert git.is_git_repo() is False

    def test_nonexistent_path_returns_false(self, tmp_path):
        """不存在路径返回 False。"""
        git = GitIntegration(str(tmp_path / "nonexistent"))
        assert git.is_git_repo() is False


class TestGetCurrentBranch:
    """get_current_branch: 获取当前分支。"""

    def test_returns_branch_name(self, git_repo):
        """返回当前分支名。"""
        git = GitIntegration(str(git_repo))
        branch = git.get_current_branch()
        # git init 后默认分支可能是 master 或 main
        assert branch in ("master", "main")

    def test_non_repo_returns_none(self, tmp_path):
        """非 git 目录返回 None。"""
        git = GitIntegration(str(tmp_path))
        assert git.get_current_branch() is None


class TestGetStatus:
    """get_status: 获取仓库状态。"""

    def test_clean_repo(self, git_repo):
        """干净仓库状态。"""
        git = GitIntegration(str(git_repo))
        status = git.get_status()
        assert status.is_repo is True
        assert status.current_branch in ("master", "main")
        assert status.modified_files == []
        assert status.staged_files == []
        assert status.untracked_files == []

    def test_untracked_file(self, git_repo):
        """未跟踪文件。"""
        (git_repo / "new_file.txt").write_text("new content")
        git = GitIntegration(str(git_repo))
        status = git.get_status()
        assert "new_file.txt" in status.untracked_files

    def test_modified_file(self, git_repo):
        """已修改文件。"""
        (git_repo / "README.md").write_text("# Modified")
        git = GitIntegration(str(git_repo))
        status = git.get_status()
        assert "README.md" in status.modified_files

    def test_staged_file(self, git_repo):
        """已暂存文件。"""
        (git_repo / "new.txt").write_text("new")
        subprocess.run(
            ["git", "add", "new.txt"], cwd=str(git_repo), check=True, capture_output=True
        )
        git = GitIntegration(str(git_repo))
        status = git.get_status()
        assert "new.txt" in status.staged_files

    def test_non_repo_status(self, tmp_path):
        """非 git 目录返回 is_repo=False。"""
        git = GitIntegration(str(tmp_path))
        status = git.get_status()
        assert status.is_repo is False


class TestGetLog:
    """get_log: 获取提交记录。"""

    def test_returns_commits(self, git_repo):
        """返回提交列表。"""
        git = GitIntegration(str(git_repo))
        commits = git.get_log()
        assert len(commits) >= 1
        assert commits[0].message == "Initial commit"
        assert commits[0].author == "Test User"
        assert len(commits[0].sha) == 40  # SHA-1 长度

    def test_limit_respected(self, git_repo):
        """limit 参数生效。"""
        # 添加更多提交
        (git_repo / "file1.txt").write_text("1")
        subprocess.run(["git", "add", "."], cwd=str(git_repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Second commit"],
            cwd=str(git_repo),
            check=True,
            capture_output=True,
        )
        (git_repo / "file2.txt").write_text("2")
        subprocess.run(["git", "add", "."], cwd=str(git_repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Third commit"],
            cwd=str(git_repo),
            check=True,
            capture_output=True,
        )

        git = GitIntegration(str(git_repo))
        commits = git.get_log(limit=2)
        assert len(commits) == 2
        # 最近的提交在前
        assert commits[0].message == "Third commit"
        assert commits[1].message == "Second commit"

    def test_non_repo_returns_empty(self, tmp_path):
        """非 git 目录返回空列表。"""
        git = GitIntegration(str(tmp_path))
        assert git.get_log() == []


class TestGetDiff:
    """get_diff: 获取变更 diff。"""

    def test_unstaged_diff(self, git_repo):
        """未暂存变更的 diff。"""
        (git_repo / "README.md").write_text("# Modified Content")
        git = GitIntegration(str(git_repo))
        diff = git.get_diff(staged=False)
        assert diff is not None
        assert "-# Test Repo" in diff
        assert "+# Modified Content" in diff

    def test_staged_diff(self, git_repo):
        """已暂存变更的 diff。"""
        (git_repo / "new.txt").write_text("new content")
        subprocess.run(
            ["git", "add", "new.txt"], cwd=str(git_repo), check=True, capture_output=True
        )
        git = GitIntegration(str(git_repo))
        diff = git.get_diff(staged=True)
        assert diff is not None
        assert "+new content" in diff

    def test_no_diff_when_clean(self, git_repo):
        """干净仓库无 diff。"""
        git = GitIntegration(str(git_repo))
        diff = git.get_diff()
        assert diff == "" or diff is None


class TestGetGitignorePatterns:
    """get_gitignore_patterns: 读取 .gitignore。"""

    def test_reads_patterns(self, git_repo):
        """读取 .gitignore 模式。"""
        (git_repo / ".gitignore").write_text(
            "*.pyc\n__pycache__/\n.env\n# comment\n"
        )
        git = GitIntegration(str(git_repo))
        patterns = git.get_gitignore_patterns()
        assert "*.pyc" in patterns
        assert "__pycache__/" in patterns
        assert ".env" in patterns
        # 注释不应包含
        assert "# comment" not in patterns

    def test_no_gitignore_returns_empty(self, git_repo):
        """无 .gitignore 返回空列表。"""
        git = GitIntegration(str(git_repo))
        assert git.get_gitignore_patterns() == []


class TestGetSummary:
    """get_summary: 获取仓库摘要。"""

    def test_repo_summary(self, git_repo):
        """仓库摘要包含必要字段。"""
        (git_repo / "modified.txt").write_text("modified")
        git = GitIntegration(str(git_repo))
        summary = git.get_summary()
        assert summary["is_repo"] is True
        assert "current_branch" in summary
        assert summary["untracked_count"] >= 1
        assert "recent_commits" in summary

    def test_non_repo_summary(self, tmp_path):
        """非仓库返回 is_repo=False。"""
        git = GitIntegration(str(tmp_path))
        summary = git.get_summary()
        assert summary == {"is_repo": False}
