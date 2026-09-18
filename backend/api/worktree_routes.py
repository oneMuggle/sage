"""会话级 worktree / 分支选择 HTTP 路由（worktree 模式 P1，2026-09-18）。

对标 Claude Code per-session worktree + Qoder worktree 模式：前端 picker
用 ``GET /branches`` 拉分支清单（含已被 worktree 占用标记），用
``POST ""`` 以 new / open / checkout 三种模式切换会话工作目录，用
``GET ""`` / ``POST /merge`` / ``DELETE /{id}`` 管理已登记的 worktree。

约定：
- worktree 目录放在主仓的兄弟目录 ``<repo>.sage-worktrees/<分支slug>-<id8>``，
  不污染仓库工作树；
- 创建/检出成功后一律 ``bind_session_workspace``（generation 自增，旧绑定
  经既有机制自动失效）；
- 复用 git_tool 面（GitBranchTool/GitStatusTool/GitCheckoutTool）与
  worktree_merge.merge_session_worktree，保持与 LLM 工具同一实现口径。
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.data.database import get_database
from backend.office.session_workspace import (
    bind_session_workspace,
    get_workspace_binding,
)
from backend.office.session_worktrees import (
    STATUS_ACTIVE,
    STATUS_DISCARDED,
    STATUS_MERGED,
    SessionWorktree,
    delete_session_worktree,
    list_session_worktrees,
    register_session_worktree,
    update_worktree_status,
)
from backend.orchestration.worktree import (
    create_worktree,
    is_git_repo,
    list_worktrees,
    prune_worktrees,
    remove_worktree,
)
from backend.orchestration.worktree_merge import (
    find_main_repo as find_main_repo_path,
    merge_session_worktree,
    sanitize_branch_suffix,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions/{session_id}/worktree", tags=["worktree"])

WORKTREES_DIR_SUFFIX = ".sage-worktrees"


class BranchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    kind: str  # local | remote
    is_current: bool
    head: str
    date: str
    subject: str
    worktree_path: Optional[str]  # 非空 = 该分支已在某 worktree 检出


class BranchesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo_root: str
    current_branch: str
    is_git: bool
    branches: List[BranchModel]
    worktrees: List["WorktreeModel"]


class WorktreeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    session_id: str
    repo_root: str
    worktree_path: str
    branch_name: Optional[str]
    base_ref: str
    status: str
    created_at: int
    updated_at: int
    is_current: bool  # 会话当前绑定就工作在这个目录


class WorktreeListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worktrees: List[WorktreeModel]


class WorktreeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # new: 以 base_ref 为基新建分支 + worktree；open: 已有本地分支检出到
    # 新 worktree；checkout: 原仓库就地切分支（要求工作区干净）。
    mode: str = Field(pattern="^(new|open|checkout)$")
    branch: str = Field(min_length=1, max_length=200)
    base_ref: str = Field(default="HEAD", min_length=1, max_length=200)


class WorktreeActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    message: str
    workspace_path: Optional[str]
    generation: Optional[int]
    worktree: Optional[WorktreeModel]


class WorktreeMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worktree_id: str = Field(min_length=1, max_length=64)


class WorktreeMergeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: dict


class WorktreeDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worktree_id: str = Field(min_length=1, max_length=64)
    delete_branch: bool = False


BranchesResponse.model_rebuild()


def _connection() -> sqlite3.Connection:
    return get_database().get_connection()


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _bound_repo_or_raise(conn: sqlite3.Connection, session_id: str) -> str:
    if (
        conn.execute(
            "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        is None
    ):
        raise _error(404, "session_not_found", "会话不存在")
    binding = get_workspace_binding(conn, session_id)
    if binding is None or not binding.workspace_path:
        raise _error(403, "workspace_not_bound", "当前会话尚未绑定工作区")
    return binding.workspace_path


def _worktree_model(
    conn: sqlite3.Connection, wt: SessionWorktree, current_path: str
) -> WorktreeModel:
    return WorktreeModel(
        id=wt.id,
        session_id=wt.session_id,
        repo_root=wt.repo_root,
        worktree_path=wt.worktree_path,
        branch_name=wt.branch_name,
        base_ref=wt.base_ref,
        status=wt.status,
        created_at=wt.created_at,
        updated_at=wt.updated_at,
        is_current=wt.worktree_path == current_path,
    )


def _session_current_path(conn: sqlite3.Connection, session_id: str) -> str:
    binding = get_workspace_binding(conn, session_id)
    return binding.workspace_path if binding else ""


def _worktrees_root(main: Path) -> Path:
    return main.parent / (main.name + WORKTREES_DIR_SUFFIX)


@router.get("/branches", response_model=BranchesResponse)
def list_branches(
    session_id: str,
    include_remote: bool = Query(default=True),
) -> BranchesResponse:
    """分支 picker 数据源：本地（+可选远端）分支、head 提交、worktree 占用。"""
    from backend.domain.tool_policy import ToolPolicy
    from backend.tools.git_tool import GitBranchTool

    conn = _connection()
    root = _bound_repo_or_raise(conn, session_id)
    main = find_main_repo_path(Path(root))
    is_repo = main is not None and is_git_repo(Path(root))
    if not is_repo:
        return BranchesResponse(
            repo_root=root, current_branch="", is_git=False, branches=[], worktrees=[]
        )
    result = GitBranchTool(ToolPolicy(workspace_root=root)).execute(
        include_remote=include_remote
    )
    if not result.success:
        raise _error(502, "git_error", result.error or "git 命令失败")
    content = result.content if isinstance(result.content, dict) else {}

    occupancy = {
        str(entry.get("branch")): str(entry.get("path"))
        for entry in list_worktrees(main)
        if entry.get("branch")
    }
    models: List[BranchModel] = []
    current_branch = ""
    for entry in content.get("branches", []):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        if entry.get("is_current") and entry.get("kind") == "local":
            current_branch = name
        models.append(
            BranchModel(
                name=name,
                kind=str(entry.get("kind", "local")),
                is_current=bool(entry.get("is_current")),
                head=str(entry.get("head", "")),
                date=str(entry.get("date", "")),
                subject=str(entry.get("subject", "")),
                worktree_path=occupancy.get(name),
            )
        )
    registered = list_session_worktrees(conn, repo_root=str(main))
    return BranchesResponse(
        repo_root=str(main),
        current_branch=current_branch,
        is_git=True,
        branches=models,
        worktrees=[
            _worktree_model(conn, wt, _session_current_path(conn, session_id))
            for wt in registered
        ],
    )


@router.get("", response_model=WorktreeListResponse)
def list_session_worktree_rows(session_id: str) -> WorktreeListResponse:
    conn = _connection()
    current = _session_current_path(conn, session_id)
    rows = list_session_worktrees(conn, session_id=session_id)
    return WorktreeListResponse(
        worktrees=[_worktree_model(conn, wt, current) for wt in rows]
    )


@router.post("", response_model=WorktreeActionResponse)
def create_or_switch(session_id: str, request: WorktreeCreateRequest) -> WorktreeActionResponse:
    from backend.tools.git_tool import _valid_ref

    conn = _connection()
    root = _bound_repo_or_raise(conn, session_id)
    if not _valid_ref(request.branch):
        raise _error(422, "invalid_branch", f"非法分支名: {request.branch!r}")

    if request.mode == "checkout":
        return _inplace_checkout(conn, session_id, root, request.branch)
    return _worktree_add(conn, session_id, root, request)


def _inplace_checkout(
    conn: sqlite3.Connection, session_id: str, root: str, branch: str
) -> WorktreeActionResponse:
    """就地切分支：工作区必须干净（避免破坏未提交工作），复用 GitCheckoutTool。"""
    from backend.domain.tool_policy import ToolPolicy
    from backend.tools.git_tool import GitCheckoutTool, GitStatusTool

    status = GitStatusTool(ToolPolicy(workspace_root=root)).execute()
    if not status.success:
        raise _error(502, "git_error", status.error or "git 命令失败")
    sc = status.content if isinstance(status.content, dict) else {}
    if not sc.get("clean", False):
        raise _error(
            409,
            "workspace_dirty",
            f"工作区有 {len(sc.get('changes', []))} 处未提交变更，请先提交或改用 worktree 模式",
        )
    result = GitCheckoutTool(ToolPolicy(workspace_root=root)).execute(branch=branch)
    if not result.success:
        raise _error(502, "git_error", result.error or "git checkout 失败")
    binding = bind_session_workspace(conn, session_id, root)
    return WorktreeActionResponse(
        ok=True,
        message=f"已就地切换到分支 {branch}",
        workspace_path=root,
        generation=binding.generation,
        worktree=None,
    )


def _worktree_add(
    conn: sqlite3.Connection,
    session_id: str,
    root: str,
    request: WorktreeCreateRequest,
) -> WorktreeActionResponse:
    main = find_main_repo_path(Path(root))
    if main is None:
        raise _error(409, "not_a_git_repo", "当前工作区不是 git 仓库，无法使用 worktree 模式")

    branch = request.branch
    existing_rows = {
        wt.branch_name: wt for wt in list_session_worktrees(conn, repo_root=str(main))
    }
    known = existing_rows.get(branch)
    if known is not None and Path(known.worktree_path).is_dir():
        # 同分支 worktree 已存在（本仓登记过）→ 幂等重绑，不重复建目录
        binding = bind_session_workspace(conn, session_id, known.worktree_path)
        return WorktreeActionResponse(
            ok=True,
            message=f"已切换到分支 {branch} 的既有 worktree",
            workspace_path=known.worktree_path,
            generation=binding.generation,
            worktree=_worktree_model(conn, known, known.worktree_path),
        )

    # 目录：主仓兄弟目录下 <slug>-<id8>；分支已存在则检出（open 语义），
    # 否则以 base_ref 为基新建（new 语义）。
    slug = sanitize_branch_suffix(branch).replace("/", "-")[:60] or "wt"
    dest = _worktrees_root(main) / "{}-{}".format(slug, uuid.uuid4().hex[:8])
    branch_exists = _local_branch_exists(main, branch)
    if request.mode == "new" and branch_exists:
        raise _error(409, "branch_exists", f"分支 {branch} 已存在，请换名或选 open 模式")
    if request.mode == "open" and not branch_exists:
        raise _error(404, "branch_not_found", f"本地分支不存在: {branch}（远端分支请先 pull）")
    occupied = _branch_occupied(main, branch)
    if occupied:
        raise _error(409, "branch_checked_out", f"分支 {branch} 已在 {occupied} 检出")

    ok = create_worktree(
        main, dest, branch=branch, base_ref=request.base_ref, create_branch=not branch_exists
    )
    if not ok:
        logger.warning("worktree add 失败 repo=%s dest=%s branch=%s", main, dest, branch)
        raise _error(502, "worktree_create_failed", "git worktree 创建失败，请查看后端日志")
    row = register_session_worktree(
        conn,
        session_id=session_id,
        repo_root=str(main),
        worktree_path=str(dest),
        branch_name=branch,
        base_ref=request.base_ref if not branch_exists else "HEAD",
    )
    binding = bind_session_workspace(conn, session_id, str(dest))
    return WorktreeActionResponse(
        ok=True,
        message=f"worktree 已就绪（分支 {branch}）",
        workspace_path=str(dest),
        generation=binding.generation,
        worktree=_worktree_model(conn, row, str(dest)),
    )


def _local_branch_exists(main: Path, branch: str) -> bool:
    return _git_ok(["rev-parse", "--verify", "refs/heads/" + branch], main)


def _branch_occupied(main: Path, branch: str) -> Optional[str]:
    for entry in list_worktrees(main):
        if entry.get("branch") == branch:
            return str(entry.get("path"))
    return None


def _git_ok(args: List[str], cwd: Path) -> bool:
    import subprocess

    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            timeout=30,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@router.post("/merge", response_model=WorktreeMergeResponse)
def merge_worktree(session_id: str, request: WorktreeMergeRequest) -> WorktreeMergeResponse:
    conn = _connection()
    _bound_repo_or_raise(conn, session_id)
    row = _worktree_row_or_raise(conn, request.worktree_id, session_id)
    if row.branch_name is None:
        raise _error(422, "no_branch", "该 worktree 无命名分支，无法合并")
    result = merge_session_worktree(
        row.worktree_path, branch=row.branch_name, label="session:" + session_id[:12]
    )
    if result.ok and result.code == "merged":
        update_worktree_status(conn, row.id, STATUS_MERGED)
    return WorktreeMergeResponse(result=result.to_dict())


@router.delete("/{worktree_id}", response_model=WorktreeActionResponse)
def remove_session_worktree(
    session_id: str, worktree_id: str, delete_branch: bool = Query(default=False)
) -> WorktreeActionResponse:
    conn = _connection()
    _bound_repo_or_raise(conn, session_id)
    row = _worktree_row_or_raise(conn, worktree_id, session_id)

    remove_worktree(Path(row.worktree_path))
    if delete_branch and row.branch_name:
        _git_ok(["branch", "-D", row.branch_name], Path(row.repo_root))
    delete_session_worktree(conn, row.id)

    # 会话正绑定在被删目录 → 退回主仓，generation 自增使旧工具面失效
    current = _session_current_path(conn, session_id)
    rebound: Optional[str] = None
    generation: Optional[int] = None
    if current == row.worktree_path:
        main = find_main_repo_path(Path(row.repo_root))
        target = str(main) if main is not None else row.repo_root
        binding = bind_session_workspace(conn, session_id, target)
        rebound = target
        generation = binding.generation
    return WorktreeActionResponse(
        ok=True,
        message="worktree 已移除" + (f"，会话已切回 {rebound}" if rebound else ""),
        workspace_path=rebound,
        generation=generation,
        worktree=None,
    )


def _worktree_row_or_raise(
    conn: sqlite3.Connection, worktree_id: str, session_id: str
) -> SessionWorktree:
    for row in list_session_worktrees(conn, session_id=session_id):
        if row.id == worktree_id:
            return row
    raise _error(404, "worktree_not_found", "该会话下不存在此 worktree 登记")


def sweep_registered_worktrees(conn: sqlite3.Connection) -> int:
    """启动对账：登记为 active 但目录已在盘上被删的 worktree → 标 discarded。

    同时 ``worktree prune`` 清主仓悬空元数据；若会话绑定还指向已删目录，
    退回主仓（generation 自增，避免工具面继续用死路径）。返回处理条数。
    """
    swept = 0
    for row in list_session_worktrees(conn, status=STATUS_ACTIVE):
        if Path(row.worktree_path).is_dir():
            continue
        update_worktree_status(conn, row.id, STATUS_DISCARDED)
        main = find_main_repo_path(Path(row.worktree_path)) or Path(row.repo_root)
        if main.is_dir():
            prune_worktrees(main)
        binding = get_workspace_binding(conn, row.session_id)
        if binding is not None and binding.workspace_path == row.worktree_path:
            target = str(main) if main.is_dir() else row.repo_root
            try:
                bind_session_workspace(conn, row.session_id, target)
            except Exception:  # noqa: BLE001 — 会话可能已删除，跳过重绑
                logger.debug("worktree 对账重绑跳过 session=%s", row.session_id)
        swept += 1
    return swept
