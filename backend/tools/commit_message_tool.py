"""commit message 生成辅助工具（对标增强 Phase-2 G9，docs/plans §2.1）。

对标 Codex / Qoder 的 commit message 生成：把 ``git diff --staged`` 的
结构化摘要（变更文件清单 + 每文件统计 + 截断 diff）交给调用方 LLM，
由它撰写符合项目惯例的 message —— 工具本身不做 LLM 调用（run_loop 内
再起 LLM 会递归阻塞），只负责把"看懂改动"所需的信息一次给全。

READ 风险：只读暂存区与最近提交历史（供 LLM 对齐既有 message 风格），
不写任何状态。与 git_commit 配套：generate → 写 message → git_commit。
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from backend.domain.risk import RiskClass

from .base import ToolResult, ToolSchema
from .git_tool import GIT_TIMEOUT_SECONDS, GitToolBase

logger = logging.getLogger(__name__)

#: 交给 LLM 的 diff 截断上限（字节）—— 足够看清改动，不撑爆上下文
_DIFF_CAP_BYTES = 16 * 1024

#: numstat 输出上限（防御性：超大变更集不拖垮 payload）
_MAX_NUMSTAT_ENTRIES = 200


def _run_git(args: List[str], cwd: str) -> Tuple[Optional[str], Optional[str]]:
    """与 git_tool 同口径的 git 子进程执行（仅读命令）。"""
    try:
        completed = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, timeout=GIT_TIMEOUT_SECONDS, check=False
        )
    except FileNotFoundError:
        return None, "git 可执行文件不可用：请确认 git 已安装并在 PATH 中"
    except subprocess.TimeoutExpired:
        return None, f"git 命令超时（{GIT_TIMEOUT_SECONDS:.0f} 秒）"
    except OSError as exc:
        return None, f"git 命令启动失败: {exc}"
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        stdout = completed.stdout.decode("utf-8", errors="replace").strip()
        return None, stderr or stdout or f"git 退出码 {completed.returncode}"
    return completed.stdout.decode("utf-8", errors="replace"), None


class GitCommitMessageTool(GitToolBase):
    """汇总暂存区改动 + 最近提交风格，为 commit message 撰写提供素材。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="git_commit_message",
            description=(
                "为即将进行的提交生成 commit message 素材：返回暂存区变更的"
                "文件清单与统计、截断的 staged diff、最近 10 条提交的 message"
                "（供对齐项目既有风格）。看完素材后自行撰写 message，"
                "再用 git_commit 提交。只读操作。"
            ),
            parameters={"type": "object", "properties": {}, "required": []},
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        if kwargs:
            return ToolResult(success=False, error="git_commit_message 不接受参数")

        root, rejection = self._resolve_repo_root()
        if rejection is not None:
            return rejection

        numstat_raw, error = _run_git(["diff", "--staged", "--numstat"], root)
        if error is not None:
            return ToolResult(success=False, error=error)

        files: List[Dict[str, Any]] = []
        for line in (numstat_raw or "").splitlines()[:_MAX_NUMSTAT_ENTRIES]:
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            added, deleted, path = parts[0], parts[1], parts[2]
            files.append(
                {
                    "path": path,
                    "added": None if added == "-" else added,
                    "deleted": None if deleted == "-" else deleted,
                }
            )

        if not files:
            return ToolResult(
                success=False,
                error="暂存区为空：先用 git_commit 的 paths/add_all 暂存，"
                "或直接把要提交的文件交给 git_commit",
            )

        diff_raw, error = _run_git(["diff", "--staged", "--no-color"], root)
        if error is not None:
            return ToolResult(success=False, error=error)
        truncated = len(diff_raw) > _DIFF_CAP_BYTES

        log_raw, error = _run_git(
            ["log", "-10", "--pretty=format:%s"], root
        )
        # 历史读取失败不致命（新仓库可能没有任何提交）—— 降级为空列表
        recent_subjects = (
            [line for line in log_raw.splitlines() if line.strip()]
            if error is None and log_raw
            else []
        )

        return ToolResult(
            success=True,
            content={
                "files": files,
                "file_count": len(files),
                "diff": diff_raw[:_DIFF_CAP_BYTES],
                "diff_truncated": truncated,
                "recent_subjects": recent_subjects,
                "hint": (
                    "请依据上述改动与 recent_subjects 的风格撰写 commit message；"
                    "写好后调用 git_commit（message 必填）。"
                ),
            },
        )


__all__ = ["GitCommitMessageTool"]
