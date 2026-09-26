"""Typed HTTP routes for git status of a workspace directory.

参考 ZCode 的 workspace-file-tree (git status 标记) 设计，
为 Sage 侧边栏提供轻量级 Git Status 面板数据。

端点:
  GET /api/v1/git/status?path=<workspace_path>

返回当前分支 + 变更文件列表（modified/staged/untracked/conflicted）。
非 git 目录返回空列表（不报错），UI 静默降级。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/git", tags=["git"])


class GitFileChange(BaseModel):
    """单个文件变更。"""

    model_config = ConfigDict(extra="forbid")

    path: str
    status: str  # modified | staged | untracked | conflicted | deleted | renamed


class GitStatusResponse(BaseModel):
    """Git status 响应。"""

    model_config = ConfigDict(extra="forbid")

    branch: Optional[str] = None
    ahead: int = 0
    behind: int = 0
    files: List[GitFileChange] = []
    is_git_repo: bool = True


# Porcelain status 字符 → 语义状态映射
_STATUS_MAP = {
    "M": "modified",
    "A": "staged",
    "D": "deleted",
    "R": "renamed",
    "C": "staged",  # copied
    "?": "untracked",
    "U": "conflicted",
}


def _run_git(cwd: str, args: List[str], timeout: float = 5.0) -> Tuple[int, str]:
    """在指定目录运行 git 命令，返回 (returncode, stdout)。"""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout
    except subprocess.TimeoutExpired:
        logger.warning("git %s timed out in %s", args, cwd)
        return 1, ""
    except FileNotFoundError:
        logger.warning("git binary not found")
        return 1, ""
    except Exception as e:
        logger.warning("git %s failed in %s: %s", args, cwd, e)
        return 1, ""


def _parse_porcelain_line(line: str) -> Optional[GitFileChange]:
    """解析 porcelain v1 状态行（XY path 或 XY \"path with spaces\"）。"""
    if len(line) < 4:
        return None
    x, y = line[0], line[1]
    # 取路径（处理引号包裹的空格路径）
    raw_path = line[3:]
    if raw_path.startswith('"') and raw_path.endswith('"'):
        raw_path = raw_path[1:-1]

    # 优先级: conflicted > staged (index) > working tree
    if x == "U" or y == "U" or (x == "A" and y == "A") or (x == "D" and y == "D"):
        status = "conflicted"
    elif x not in {" ", "?"}:
        status = "staged"
    elif y not in {" ", "?"}:
        status = _STATUS_MAP.get(y, "modified")
    elif x == "?":
        status = "untracked"
    else:
        return None

    return GitFileChange(path=raw_path, status=status)


def _get_branch_info(cwd: str) -> Tuple[Optional[str], int, int]:
    """获取当前分支名和 ahead/behind 数。"""
    # 分支名
    rc, out = _run_git(cwd, ["rev-parse", "--abbrev-ref", "HEAD"])
    branch = out.strip() if rc == 0 else None
    if branch == "HEAD":
        branch = None  # detached HEAD

    # ahead/behind (需要 upstream)
    ahead, behind = 0, 0
    if branch:
        rc2, out2 = _run_git(cwd, ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"])
        if rc2 == 0:
            parts = out2.strip().split("\t")
            if len(parts) == 2:
                try:
                    ahead = int(parts[0])
                    behind = int(parts[1])
                except ValueError:
                    pass
    return branch, ahead, behind


@router.get("/status", response_model=GitStatusResponse)
def get_git_status(
    path: str = Query(..., min_length=1, description="Workspace directory path"),
) -> GitStatusResponse:
    """获取指定目录的 git status。

    非 git 目录返回 is_git_repo=false，空文件列表（不报错）。
    """
    workspace = Path(path).resolve()
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail=f"Directory not found: {path}")

    # 检查是否为 git 仓库
    rc, _ = _run_git(str(workspace), ["rev-parse", "--git-dir"])
    if rc != 0:
        return GitStatusResponse(is_git_repo=False, files=[])

    # 分支信息
    branch, ahead, behind = _get_branch_info(str(workspace))

    # 文件状态
    rc2, out = _run_git(str(workspace), ["status", "--porcelain"])
    if rc2 != 0:
        return GitStatusResponse(branch=branch, ahead=ahead, behind=behind, files=[])

    files: List[GitFileChange] = []
    for line in out.splitlines():
        change = _parse_porcelain_line(line)
        if change:
            files.append(change)

    # 排序优先级——conflicted 最前, renamed 最后
    status_order = {"conflicted": 0, "staged": 1, "modified": 2, "untracked": 3, "deleted": 4, "renamed": 5}
    files.sort(key=lambda f: (status_order.get(f.status, 99), f.path))

    return GitStatusResponse(
        branch=branch,
        ahead=ahead,
        behind=behind,
        files=files,
        is_git_repo=True,
    )
