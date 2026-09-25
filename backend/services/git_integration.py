"""Git 只读集成服务（项目类型分类系统，2026-09-24）。

为 coding 类型项目提供 Git 仓库的只读操作，用于向 LLM 注入版本控制上下文。
与 `git_tool.py`（LLM 调用的工具）不同，本模块是系统服务，供后端逻辑使用。

设计原则:
- 只读操作：不修改仓库状态（不 commit/push/reset）
- 失败静默：任何异常返回空/默认值，不抛出
- subprocess 参数列表调用（不经 shell，跨平台一致）
- 超时保护：所有 git 命令 30 秒超时
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

#: git 可执行文件
GIT_BINARY = "git"

#: 超时秒数
GIT_TIMEOUT_SECONDS = 30.0

#: 日志字段分隔符
_LOG_FIELD_SEP = "\x1f"
_LOG_PRETTY = f"%H{_LOG_FIELD_SEP}%an{_LOG_FIELD_SEP}%ci{_LOG_FIELD_SEP}%s"


@dataclass
class GitStatus:
    """Git 仓库状态。"""

    is_repo: bool = False
    current_branch: Optional[str] = None
    modified_files: List[str] = field(default_factory=list)
    staged_files: List[str] = field(default_factory=list)
    untracked_files: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "is_repo": self.is_repo,
            "current_branch": self.current_branch,
            "modified_files": self.modified_files,
            "staged_files": self.staged_files,
            "untracked_files": self.untracked_files,
        }


@dataclass
class GitCommit:
    """Git 提交记录。"""

    sha: str
    author: str
    date: str
    message: str

    def to_dict(self) -> dict:
        return {
            "sha": self.sha,
            "author": self.author,
            "date": self.date,
            "message": self.message,
        }


def _run_git(args: List[str], cwd: str) -> Optional[str]:
    """执行 git 命令，返回 stdout 或 None（失败时）。"""
    try:
        completed = subprocess.run(
            [GIT_BINARY, *args],
            cwd=cwd,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode != 0:
            return None
        return completed.stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("git command failed: %s", exc)
        return None


class GitIntegration:
    """Git 只读集成服务。

    为 coding 类型项目提供版本控制上下文注入。所有方法失败时返回空/默认值，
    不抛出异常。
    """

    def __init__(self, repo_path: str) -> None:
        """初始化。

        Args:
            repo_path: Git 仓库路径
        """
        self.repo_path = repo_path

    def is_git_repo(self) -> bool:
        """检查路径是否为 Git 仓库。"""
        result = _run_git(["rev-parse", "--git-dir"], self.repo_path)
        return result is not None

    def get_current_branch(self) -> Optional[str]:
        """获取当前分支名。"""
        result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], self.repo_path)
        if result is None:
            return None
        return result.strip()

    def get_status(self) -> GitStatus:
        """获取仓库状态。"""
        if not self.is_git_repo():
            return GitStatus(is_repo=False)

        status = GitStatus(is_repo=True)
        status.current_branch = self.get_current_branch()

        # git status --porcelain=v1 输出格式稳定，易于解析
        result = _run_git(["status", "--porcelain=v1"], self.repo_path)
        if result is None:
            return status

        # 注意：不能用 strip()，因为行首的空格是状态的一部分
        # 只移除末尾的空白行
        lines = result.rstrip("\n").split("\n")
        for line in lines:
            if not line or len(line) < 3:
                continue
            # 格式: XY filename
            # X = 暂存区状态, Y = 工作区状态  # noqa: ERA001
            # 常见状态:
            #   " M" = 未暂存修改 (modified in work tree)
            #   "M " = 已暂存修改 (modified in index)
            #   "?? " = 未跟踪文件
            #   "A " = 已暂存新增
            #   "D " = 已暂存删除
            xy = line[:2]
            # 跳过 XY 后的空格
            filename = line[3:] if line[2] == " " else line[2:]

            # 暂存区有变更 (X 不是空格且不是 ?)
            if xy[0] not in (" ", "?"):
                status.staged_files.append(filename)
            # 工作区有变更 (Y 不是空格)
            if xy[1] != " ":
                status.modified_files.append(filename)
            # 未跟踪文件
            if xy == "??":
                status.untracked_files.append(filename)

        return status

    def get_log(self, limit: int = 10) -> List[GitCommit]:
        """获取最近提交记录。

        Args:
            limit: 最多返回的提交数（默认 10）
        """
        if not self.is_git_repo():
            return []

        result = _run_git(
            ["log", f"-{limit}", f"--pretty=format:{_LOG_PRETTY}"],
            self.repo_path,
        )
        if result is None:
            return []

        commits = []
        for line in result.strip().split("\n"):
            if not line:
                continue
            parts = line.split(_LOG_FIELD_SEP)
            if len(parts) >= 4:
                commits.append(
                    GitCommit(
                        sha=parts[0],
                        author=parts[1],
                        date=parts[2],
                        message=parts[3],
                    )
                )
        return commits

    def get_diff(self, staged: bool = False) -> Optional[str]:
        """获取当前变更的 diff。

        Args:
            staged: True 返回已暂存的变更，False 返回未暂存的变更
        """
        if not self.is_git_repo():
            return None

        args = ["diff"]
        if staged:
            args.append("--staged")
        return _run_git(args, self.repo_path)

    def get_gitignore_patterns(self) -> List[str]:
        """读取 .gitignore 文件的忽略模式。"""
        gitignore_path = Path(self.repo_path) / ".gitignore"
        if not gitignore_path.is_file():
            return []
        try:
            content = gitignore_path.read_text(encoding="utf-8")
            patterns = []
            for line in content.split("\n"):
                line = line.strip()  # noqa: PLW2901
                # 跳过空行和注释
                if line and not line.startswith("#"):
                    patterns.append(line)
            return patterns
        except OSError as exc:
            logger.debug("Failed to read .gitignore: %s", exc)
            return []

    def get_summary(self) -> dict:
        """获取仓库摘要（用于注入 system prompt）。

        Returns:
            包含分支、状态、最近提交的字典
        """
        status = self.get_status()
        if not status.is_repo:
            return {"is_repo": False}

        log = self.get_log(limit=5)
        return {
            "is_repo": True,
            "current_branch": status.current_branch,
            "modified_count": len(status.modified_files),
            "staged_count": len(status.staged_files),
            "untracked_count": len(status.untracked_files),
            "recent_commits": [c.to_dict() for c in log],
        }


__all__ = [
    "GitCommit",
    "GitIntegration",
    "GitStatus",
]
