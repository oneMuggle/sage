"""``worktree_merge`` — A4 接受语义：把 lane worktree 的变更合回主工作区。

lane worktree 是 ``--detach`` 空分支副本（见 worktree.py）：只隔离、不自动
合并。用户在交付包点"接受"后，本模块执行：

1. 定位主仓（worktree 自知的 ``--git-common-dir``，无外部配置）；
2. 主仓必须干净（脏 → 拒绝，用户先提交）；
3. worktree 内建分支 ``lane/accept/<lane>-<rand>``（add -A + commit，
   记录 base HEAD 备审计；分支保留不删，便于回看/回滚）；
4. 主仓 ``merge --no-ff`` → 冲突则 abort + 返回冲突文件列表。

fail-closed 铁律：任何前置不满足都拒绝合并不动双方；conflicts/dirty
可重试；调用方（decision 路由）负责事件与清理。全部 git 调用有超时保护，
无 shell=True，py3.8 兼容写法。
"""

from __future__ import annotations

import logging
import re
import subprocess
import uuid
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_GIT_TIMEOUT_S = 30
ACCEPT_IDENTITY_NAME = "Sage Accept"
ACCEPT_IDENTITY_EMAIL = "accept@local.sage"
_BRANCH_SAFE_RE = re.compile(r"[^A-Za-z0-9._/-]+")
_MAX_FILES_LISTED = 200


@dataclass
class MergeResult:
    """接受合并结论。code 语义见 accept_lane_worktree 文档。"""

    ok: bool
    code: str
    message: str = ""
    branch: str = ""
    base_head: str = ""
    merge_head: str = ""
    files_changed: List[str] = dc_field(default_factory=list)
    conflict_files: List[str] = dc_field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "code": self.code,
            "message": self.message,
            "branch": self.branch,
            "base_head": self.base_head,
            "merge_head": self.merge_head,
            "files_changed": self.files_changed,
            "conflict_files": self.conflict_files,
        }


def _run_git(
    args: List[str], cwd: Path, timeout_s: int = _GIT_TIMEOUT_S
) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(
            # 编码铁律：git for windows 输出恒 UTF-8，必须显式解码——
            # text=True 默认走 GBK locale，非 ASCII 路径会乱码导致路径判定失效；
            # core.quotepath=false 让非 ASCII 文件名不被八进制转义。
            ["git", "-c", "core.quotepath=false", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("git %s 失败: %s", args[:2], exc)
        return None


def _is_git_repo(path: Path) -> bool:
    proc = _run_git(["rev-parse", "--is-inside-work-tree"], path)
    return proc is not None and proc.returncode == 0


def find_main_repo(worktree: Path) -> Optional[Path]:
    """worktree 自知的主仓路径；失败返 None。"""
    proc = _run_git(
        ["rev-parse", "--path-format=absolute", "--git-common-dir"], worktree
    )
    if proc is None or proc.returncode != 0:
        return None
    common = Path(proc.stdout.strip())
    main = common.parent if common.name == ".git" else common
    if not main.is_dir() or not _is_git_repo(main):
        return None
    return main


def _status_porcelain(repo: Path) -> Optional[List[str]]:
    proc = _run_git(["status", "--porcelain"], repo)
    if proc is None or proc.returncode != 0:
        return None
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def _identity_args(repo: Path) -> List[str]:
    """仓库缺 user.* 身份时返回 -c 回退（不写用户配置）。"""
    proc = _run_git(["config", "user.email"], repo)
    if proc is not None and proc.returncode == 0 and proc.stdout.strip():
        return []
    return [
        "-c",
        f"user.email={ACCEPT_IDENTITY_EMAIL}",
        "-c",
        f"user.name={ACCEPT_IDENTITY_NAME}",
    ]


def sanitize_branch_suffix(raw: str) -> str:
    return _BRANCH_SAFE_RE.sub("-", raw).strip("-") or "lane"


def accept_lane_worktree(
    worktree: str, *, lane_id: str, main_repo: Optional[str] = None
) -> MergeResult:
    """执行接受合并。永不抛错（超时/IO 转 git-error）。

    code：merged（已合）| no-changes（无变更，无需合）|
    worktree-missing | not-a-repo | main-not-found | not-a-worktree |
    main-dirty | conflicts | git-error。
    """
    try:
        return _accept_inner(worktree, lane_id=lane_id, main_repo=main_repo)
    except Exception as exc:  # noqa: BLE001 — 合并绝不能抛错给路由
        logger.warning("accept 合并异常 lane=%s: %s", lane_id, exc)
        return MergeResult(ok=False, code="git-error", message=f"合并异常：{exc}")


def _accept_inner(  # noqa: PLR0911 — fail-closed 多拒绝分支是设计
    worktree: str, *, lane_id: str, main_repo: Optional[str]
) -> MergeResult:
    wt = Path(worktree)
    if not wt.is_dir():
        return MergeResult(
            ok=False, code="worktree-missing", message=f"worktree 已不存在：{worktree}"
        )
    if not _is_git_repo(wt):
        return MergeResult(ok=False, code="not-a-repo", message="worktree 不是 git 仓库")
    main = Path(main_repo) if main_repo else find_main_repo(wt)
    if main is None or not _is_git_repo(main):
        return MergeResult(ok=False, code="main-not-found", message="定位主仓失败")
    try:
        same = wt.resolve() == main.resolve()
    except OSError:
        same = False
    if same:
        return MergeResult(ok=False, code="not-a-worktree", message="拒绝把仓库合进自己")

    main_status = _status_porcelain(main)
    if main_status is None:
        return MergeResult(ok=False, code="git-error", message="读取主仓状态失败")
    if main_status:
        preview = "、".join(s[:60] for s in main_status[:5])
        return MergeResult(
            ok=False,
            code="main-dirty",
            message=f"主工作区有 {len(main_status)} 处未提交变更，请先提交：{preview}",
        )

    head = _run_git(["rev-parse", "HEAD"], wt)
    if head is None or head.returncode != 0:
        return MergeResult(ok=False, code="git-error", message="读取 worktree HEAD 失败")
    base_head = head.stdout.strip()

    wt_status = _status_porcelain(wt)
    if wt_status is None:
        return MergeResult(ok=False, code="git-error", message="读取 worktree 状态失败")
    if not wt_status:
        return MergeResult(
            ok=True, code="no-changes", message="无文件变更，无需合并", base_head=base_head
        )

    branch = f"lane/accept/{sanitize_branch_suffix(lane_id)}-{uuid.uuid4().hex[:8]}"
    mkbranch = _run_git(["checkout", "-b", branch], wt)
    if mkbranch is None or mkbranch.returncode != 0:
        return MergeResult(
            ok=False, code="git-error", message="worktree 建分支失败", base_head=base_head
        )
    _run_git(["add", "-A"], wt)
    commit = _run_git(
        _identity_args(wt)
        + ["commit", "-m", f"A4 accept {lane_id}", "-m", f"base: {base_head}"],
        wt,
    )
    if commit is None or commit.returncode != 0:
        _run_git(["checkout", "--detach", "HEAD"], wt)  # best-effort 复位
        tail = (commit.stderr if commit else "") or ""
        return MergeResult(
            ok=False,
            code="git-error",
            message=f"worktree 提交失败：{tail.strip()[-300:]}",
            branch=branch,
            base_head=base_head,
        )

    merged = _run_git(
        _identity_args(main) + ["merge", "--no-ff", "--no-edit", branch], main
    )
    if merged is None or merged.returncode != 0:
        conflicts = _conflict_files(main)
        _run_git(["merge", "--abort"], main)  # best-effort 回滚
        detail = "、".join(conflicts[:10]) if conflicts else "未知文件"
        return MergeResult(
            ok=False,
            code="conflicts",
            message=f"合并冲突（{len(conflicts)} 个文件），已回滚：{detail}",
            branch=branch,
            base_head=base_head,
            conflict_files=conflicts,
        )

    merge_head = ""
    mhead = _run_git(["rev-parse", "HEAD"], main)
    if mhead is not None and mhead.returncode == 0:
        merge_head = mhead.stdout.strip()
    files: List[str] = []
    diff = _run_git(["diff", "--name-only", base_head, merge_head or "HEAD"], main)
    if diff is not None and diff.returncode == 0:
        files = [ln for ln in diff.stdout.splitlines() if ln.strip()][
            :_MAX_FILES_LISTED
        ]
    return MergeResult(
        ok=True,
        code="merged",
        message=f"已合并 {len(files)} 个文件（分支 {branch} 已保留备审计）",
        branch=branch,
        base_head=base_head,
        merge_head=merge_head,
        files_changed=files,
    )


def _conflict_files(main: Path) -> List[str]:
    proc = _run_git(["diff", "--name-only", "--diff-filter=U"], main)
    if proc is None or proc.returncode != 0:
        return []
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()][
        :_MAX_FILES_LISTED
    ]
