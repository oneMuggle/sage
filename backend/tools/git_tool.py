"""一等 Git 工具组（对标增强方案 Phase-1 T1，docs/plans/2026-09-06）。

Codex / ZCode / Qoder 都把 git 以工具面暴露给 LLM：结构化结果、按操作
分级审批（读免审、commit 走 WRITE_LOCAL 审批）。此前 Sage 的 LLM 只能经
bash 拼裸 git 命令 —— 引号/转义易错、输出不可解析、无法按操作粒度门禁。

实现口径：

- ``subprocess.run`` **参数列表**调用 git（不经 shell，Windows/Linux 一致）；
- 仓库根 = ``policy.workspace_root``（未绑定工作区直接报错）；
- 超时 30s；stderr 经 utf-8 ``errors="replace"`` 解码；
- ``git_commit`` 只 add + commit，**绝不 push**。
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from backend.domain.risk import RiskClass

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

#: git 可执行文件（测试可 monkeypatch 注入）
GIT_BINARY = "git"

#: git 子进程超时（秒）—— status/diff/log/commit 都应是秒级操作
GIT_TIMEOUT_SECONDS = 30.0

#: git_diff 输出截断上限（字节）
GIT_DIFF_OUTPUT_CAP = 64 * 1024

#: git_log 单次最多返回的提交数
GIT_LOG_MAX_LIMIT = 100

#: %x1f = ASCII Unit Separator —— 字段分隔符，杜绝提交信息内嵌分隔歧义
_LOG_FIELD_SEP = "\x1f"
_LOG_PRETTY = f"%H{_LOG_FIELD_SEP}%an{_LOG_FIELD_SEP}%ci{_LOG_FIELD_SEP}%s"

_BRANCH_RE = re.compile(r"^## (?P<branch>[^\s.]+)(?:\.\.\.(?P<upstream>\S+))?(?:\s+\[(?P<track>[^\]]+)\])?")


def _run_git(args: List[str], cwd: str) -> Tuple[Optional[str], Optional[str]]:
    """执行 git 子命令；返回 (stdout, error)。error 非 None 时 stdout 无意义。"""
    try:
        completed = subprocess.run(
            [GIT_BINARY, *args],
            cwd=cwd,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return None, "git 可执行文件不可用：请确认 git 已安装并在 PATH 中"
    except subprocess.TimeoutExpired:
        return None, f"git 命令超时（{GIT_TIMEOUT_SECONDS:.0f} 秒）"
    except OSError as exc:
        return None, f"git 命令启动失败: {exc}"

    if completed.returncode != 0:
        # git 的部分失败信息走 stdout（如 "nothing to commit"），stderr 为空
        # 时回退读 stdout，保证 LLM 拿到可判读的原因
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        stdout_tail = completed.stdout.decode("utf-8", errors="replace").strip()
        detail = stderr or stdout_tail
        return None, detail or f"git 退出码 {completed.returncode}"
    return completed.stdout.decode("utf-8", errors="replace"), None


class GitToolBase(BaseTool):
    """git 工具公共基座：仓库根解析 + 路径守卫。"""

    def _resolve_repo_root(self) -> Tuple[Optional[str], Optional[ToolResult]]:
        """返回 (repo_root, None) 或 (None, 拒绝结果)。"""
        root = self._policy.workspace_root
        if not root:
            return None, ToolResult(
                success=False,
                error="git 工具需要绑定工作区（workspace）才能定位仓库根",
            )
        return root, None

    def _guard_path(self, root: str, path: str) -> Optional[ToolResult]:
        """path 参数既过 workspace 守卫，也保证按仓库根解析（防 cwd 漂移）。"""
        absolute = os.path.abspath(os.path.join(root, path))
        return self._enforce_workspace(absolute)


class GitStatusTool(GitToolBase):
    """查看工作区 git 状态（分支 / 领先落后 / 变更清单）。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="git_status",
            description=(
                "查看当前工作区的 git 状态：分支、与上游的领先/落后、"
                "未提交变更清单（暂存区与工作区分列）。只读操作。"
            ),
            parameters={"type": "object", "properties": {}, "required": []},
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        if kwargs:
            return ToolResult(success=False, error="git_status 不接受参数")

        root, rejection = self._resolve_repo_root()
        if rejection is not None:
            return rejection

        stdout, error = _run_git(["status", "--porcelain=v1", "-b"], root)
        if error is not None:
            return ToolResult(success=False, error=error)

        lines = stdout.splitlines()
        entries: List[Dict[str, str]] = []
        branch = ""
        upstream = ""
        ahead = 0
        behind = 0
        for line in lines:
            if line.startswith("##"):
                match = _BRANCH_RE.match(line)
                if match:
                    branch = match.group("branch") or ""
                    upstream = match.group("upstream") or ""
                    track = match.group("track") or ""
                    ahead_match = re.search(r"ahead (\d+)", track)
                    behind_match = re.search(r"behind (\d+)", track)
                    ahead = int(ahead_match.group(1)) if ahead_match else 0
                    behind = int(behind_match.group(1)) if behind_match else 0
                continue
            if not line.strip():
                continue
            # porcelain v1: XY <path>；重命名行是 "R  old -> new"，保留原文
            entries.append(
                {
                    "index_status": line[:1].strip(),
                    "worktree_status": line[1:2].strip(),
                    "path": line[3:],
                }
            )
        return ToolResult(
            success=True,
            content={
                "branch": branch,
                "upstream": upstream,
                "ahead": ahead,
                "behind": behind,
                "changes": entries,
                "clean": not entries,
            },
        )


class GitDiffTool(GitToolBase):
    """查看未提交变更的 diff（可选暂存区 / 指定路径）。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="git_diff",
            description=(
                "查看 git 未提交变更的 unified diff。默认看工作区相对 HEAD 的"
                "变更；staged=true 只看已暂存部分；path 可限定单个文件/目录。"
                "只读操作，输出超长时截断并标记 truncated。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "staged": {"type": "boolean", "description": "只看已暂存（--staged）的变更"},
                    "path": {"type": "string", "description": "限定路径（相对仓库根，可选）"},
                },
                "required": [],
            },
        )

    def execute(
        self,
        staged: bool = False,
        path: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if kwargs:
            names = ", ".join(sorted(kwargs))
            return ToolResult(
                success=False,
                error=f"未知参数: {names}（合法参数: staged, path）",
            )

        root, rejection = self._resolve_repo_root()
        if rejection is not None:
            return rejection

        git_args = ["diff", "--no-color"]
        if staged:
            git_args.append("--staged")
        if path:
            rejection = self._guard_path(root, path)
            if rejection is not None:
                return rejection
            git_args += ["--", path]

        stdout, error = _run_git(git_args, root)
        if error is not None:
            return ToolResult(success=False, error=error)

        truncated = len(stdout) > GIT_DIFF_OUTPUT_CAP
        return ToolResult(
            success=True,
            content={
                "diff": stdout[:GIT_DIFF_OUTPUT_CAP],
                "truncated": truncated,
            },
        )


class GitLogTool(GitToolBase):
    """查看提交历史（哈希 / 作者 / 时间 / 标题）。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="git_log",
            description=(
                "查看当前分支的提交历史，最新在前。limit 控制条数"
                f"（默认 20，上限 {GIT_LOG_MAX_LIMIT}）；path 可只看涉及某路径的提交。"
                "只读操作。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": f"返回条数（默认 20，上限 {GIT_LOG_MAX_LIMIT}）"},
                    "path": {"type": "string", "description": "限定路径（相对仓库根，可选）"},
                },
                "required": [],
            },
        )

    def execute(self, limit: int = 20, path: str = "", **kwargs: Any) -> ToolResult:
        if kwargs:
            names = ", ".join(sorted(kwargs))
            return ToolResult(
                success=False,
                error=f"未知参数: {names}（合法参数: limit, path）",
            )

        root, rejection = self._resolve_repo_root()
        if rejection is not None:
            return rejection

        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            return ToolResult(success=False, error="limit 必须是 ≥ 1 的整数")
        limit = min(limit, GIT_LOG_MAX_LIMIT)

        git_args = ["log", f"-{limit}", f"--pretty=format:{_LOG_PRETTY}"]
        if path:
            rejection = self._guard_path(root, path)
            if rejection is not None:
                return rejection
            git_args += ["--", path]

        stdout, error = _run_git(git_args, root)
        if error is not None:
            return ToolResult(success=False, error=error)

        commits: List[Dict[str, str]] = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            fields = line.split(_LOG_FIELD_SEP)
            if len(fields) != 4:
                continue
            commits.append(
                {
                    "hash": fields[0],
                    "author": fields[1],
                    "date": fields[2],
                    "subject": fields[3],
                }
            )
        return ToolResult(success=True, content={"commits": commits})


class GitCommitTool(GitToolBase):
    """暂存并提交变更（WRITE_LOCAL，INTERACTIVE 模式先经用户审批）。"""

    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="git_commit",
            description=(
                "把当前变更提交到本地仓库。paths 指定要暂存的文件（相对仓库根），"
                "add_all=true 暂存全部变更；两者都不给则直接提交已暂存内容。"
                "message 必填。只 commit，绝不 push。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "提交信息（必填）"},
                    "add_all": {"type": "boolean", "description": "暂存全部变更（git add -A）"},
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要暂存的路径列表（相对仓库根，可选）",
                    },
                },
                "required": ["message"],
            },
        )

    def execute(
        self,
        message: str = "",
        add_all: bool = False,
        paths: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if kwargs:
            names = ", ".join(sorted(kwargs))
            return ToolResult(
                success=False,
                error=f"未知参数: {names}（合法参数: message, add_all, paths）",
            )

        root, rejection = self._resolve_repo_root()
        if rejection is not None:
            return rejection
        if not isinstance(message, str) or not message.strip():
            return ToolResult(success=False, error="message 不能为空")

        checked_paths, rejection = self._validated_paths(root, paths)
        if rejection is not None:
            return rejection

        rejection = self._stage(root, add_all, checked_paths)
        if rejection is not None:
            return rejection
        return self._commit_and_hash(root, message)

    def _validated_paths(
        self, root: str, paths: Optional[List[str]]
    ) -> Tuple[List[str], Optional[ToolResult]]:
        """校验 paths 类型 + 逐路径 workspace 守卫；返回 (路径列表, 拒绝结果)。"""
        if paths is None:
            return [], None
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            return [], ToolResult(success=False, error="paths 必须是字符串列表")
        checked: List[str] = []
        for path in paths:
            rejection = self._guard_path(root, path)
            if rejection is not None:
                return [], rejection
            checked.append(path)
        return checked, None

    @staticmethod
    def _stage(root: str, add_all: bool, checked_paths: List[str]) -> Optional[ToolResult]:
        """暂存变更；失败返回携带原因的 ToolResult。"""
        if add_all:
            _, error = _run_git(["add", "-A"], root)
        elif checked_paths:
            _, error = _run_git(["add", "--", *checked_paths], root)
        else:
            return None
        if error is not None:
            return ToolResult(success=False, error=f"git add 失败: {error}")
        return None

    @staticmethod
    def _commit_and_hash(root: str, message: str) -> ToolResult:
        """commit + 回读 HEAD 哈希。"""
        _, error = _run_git(["commit", "-m", message], root)
        if error is not None:
            # 典型场景：没有可提交的变更 / 未配置 user.name —— 原样透传给 LLM
            return ToolResult(success=False, error=f"git commit 失败: {error}")

        stdout, error = _run_git(["rev-parse", "HEAD"], root)
        if error is not None:
            return ToolResult(success=False, error=f"提交完成但读取哈希失败: {error}")

        return ToolResult(
            success=True,
            content={"commit_hash": (stdout or "").strip()},
        )


__all__ = [
    "GIT_BINARY",
    "GIT_DIFF_OUTPUT_CAP",
    "GIT_LOG_MAX_LIMIT",
    "GIT_TIMEOUT_SECONDS",
    "GitCommitTool",
    "GitDiffTool",
    "GitLogTool",
    "GitStatusTool",
]
