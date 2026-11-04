"""Typed HTTP routes for git status and diff of a workspace directory.

参考 ZCode 的 workspace-file-tree (git status 标记) 设计，
为 Sage 侧边栏提供轻量级 Git Status 面板数据。

端点:
  GET /api/v1/git/status?path=<workspace_path>
  GET /api/v1/git/diff?path=<workspace_path>&file=<relative_path>

返回当前分支 + 变更文件列表（modified/staged/untracked/conflicted）。
非 git 目录返回空列表（不报错），UI 静默降级。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from backend.tools.git_status_parser import parse_status_porcelain_v1_z

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


class GitDiffResponse(BaseModel):
    """Git diff 响应。

    diff_text 为 unified diff 格式文本。
    对于 untracked 新文件，返回全部内容作为 "new file" diff。
    对于 deleted 文件，返回全部内容作为删除 diff。
    """

    model_config = ConfigDict(extra="forbid")

    file: str
    status: str  # modified | staged | untracked | deleted | conflicted | renamed
    diff_text: str
    is_new_file: bool = False
    is_deleted: bool = False


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


def _run_git(cwd: str, args: list[str], timeout: float = 5.0) -> tuple[int, str]:
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


def _parse_porcelain_line(line: str) -> GitFileChange | None:
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


def _semantic_status(index_status: str, worktree_status: str) -> Optional[str]:
    """把 porcelain 的 XY 两位状态映射成面板语义状态。

    优先级: conflicted > staged (index) > working tree > untracked。
    """
    if (
        index_status == "U"
        or worktree_status == "U"
        or (index_status == "A" and worktree_status == "A")
        or (index_status == "D" and worktree_status == "D")
    ):
        return "conflicted"
    if index_status not in {"", "?"}:
        return "staged"
    if worktree_status not in {"", "?"}:
        return _STATUS_MAP.get(worktree_status, "modified")
    if index_status == "?":
        return "untracked"
    return None


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

    # 分支 + ahead/behind + 文件状态一次拿全（-z 保留中文/空格路径）
    rc2, out = _run_git(
        str(workspace),
        ["-c", "core.quotepath=false", "status", "--porcelain=v1", "-z", "-b"],
    )
    if rc2 != 0:
        return GitStatusResponse(files=[])

    parsed = parse_status_porcelain_v1_z(out)
    branch: Optional[str] = parsed["branch"] or None
    if branch == "HEAD":  # detached HEAD
        branch = None

    files: list[GitFileChange] = []
    for entry in parsed["entries"]:
        status = _semantic_status(entry["index_status"], entry["worktree_status"])
        if status:
            files.append(GitFileChange(path=entry["path"], status=status))

    # 排序优先级——conflicted 最前, renamed 最后
    status_order = {"conflicted": 0, "staged": 1, "modified": 2, "untracked": 3, "deleted": 4, "renamed": 5}
    files.sort(key=lambda f: (status_order.get(f.status, 99), f.path))

    return GitStatusResponse(
        branch=branch,
        ahead=parsed["ahead"],
        behind=parsed["behind"],
        files=files,
        is_git_repo=True,
    )


@router.get("/diff", response_model=GitDiffResponse)
def get_git_diff(
    path: str = Query(..., min_length=1, description="Workspace directory path"),
    file: str = Query(..., min_length=1, description="Relative file path within workspace"),
) -> GitDiffResponse:
    """获取指定文件相对于 HEAD 的 unified diff。

    - tracked 文件（modified/staged/deleted/conflicted/renamed）：运行 git diff HEAD -- <file>
    - untracked 新文件：返回全部内容作为 "new file" diff
    - deleted 文件：返回被删除的内容
    - 路径穿越保护：file 参数不能逃出 workspace 目录
    """
    workspace = Path(path).resolve()
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail=f"Directory not found: {path}")

    # 路径穿越保护
    target = (workspace / file).resolve()
    try:
        target.relative_to(workspace)
    except ValueError:
        raise HTTPException(status_code=400, detail="File path escapes workspace")

    # 判断文件状态
    rc, out = _run_git(str(workspace), ["status", "--porcelain", "--", file])
    status = "modified"
    if rc == 0 and out.rstrip():
        parsed = _parse_porcelain_line(out.rstrip().split("\n")[0])
        if parsed:
            status = parsed.status

    is_new = status == "untracked"
    is_deleted = status == "deleted"

    if is_new:
        # 新文件：读取全部内容作为 diff
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        lines = content.splitlines()
        diff_lines = [f"diff --git a/{file} b/{file}", "new file mode 100644", "--- /dev/null", f"+++ b/{file}"]
        if lines:
            diff_lines.append(f"@@ -0,0 +1,{len(lines)} @@")
            diff_lines.extend(f"+{line}" for line in lines)
        diff_text = "\n".join(diff_lines) + "\n" if diff_lines else ""
    elif is_deleted:
        # 已删除文件：显示 HEAD 版本的全部内容作为删除
        rc2, head_content = _run_git(str(workspace), ["show", f"HEAD:{file}"], timeout=10.0)
        if rc2 == 0:
            lines = head_content.splitlines()
            diff_lines = [f"diff --git a/{file} b/{file}", "deleted file mode 100644", f"--- a/{file}", "+++ /dev/null"]
            if lines:
                diff_lines.append(f"@@ -1,{len(lines)} +0,0 @@")
                diff_lines.extend(f"-{line}" for line in lines)
            diff_text = "\n".join(diff_lines) + "\n"
        else:
            diff_text = ""
    else:
        # tracked 文件：git diff HEAD -- <file>
        rc3, diff_text = _run_git(str(workspace), ["diff", "HEAD", "--", file], timeout=10.0)
        if rc3 != 0:
            diff_text = ""

    return GitDiffResponse(
        file=file,
        status=status,
        diff_text=diff_text,
        is_new_file=is_new,
        is_deleted=is_deleted,
    )
