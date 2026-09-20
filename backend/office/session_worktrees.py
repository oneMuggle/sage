"""``session_worktrees`` 仓储 —— 会话级 git worktree 登记。

与 :mod:`backend.office.session_workspace` 分工：binding 表回答"会话当前
在哪个目录工作"；本表回答"sage 为该会话建过哪些 worktree、分支叫什么、
是否已合并/丢弃"，供分支 picker、合并（worktree_merge）与清理使用。

连接无关（函数收 sqlite3.Connection），与 session_workspace.py 同构，
测试可用 ``Database(":memory:")``。

status 状态机: ``active`` → ``merged`` / ``discarded``（终态不再回转）。
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

STATUS_ACTIVE = "active"
STATUS_MERGED = "merged"
STATUS_DISCARDED = "discarded"
_VALID_STATUSES = (STATUS_ACTIVE, STATUS_MERGED, STATUS_DISCARDED)


def _now_ms(now_ms: Optional[int]) -> int:
    if now_ms is None:
        return int(time.time() * 1000)
    return now_ms


@dataclass(frozen=True)
class SessionWorktree:
    """``session_worktrees`` 表的一行。"""

    id: str
    session_id: str
    repo_root: str
    worktree_path: str
    branch_name: Optional[str]
    base_ref: str
    status: str
    created_at: int
    updated_at: int


def _row_to_worktree(row: sqlite3.Row) -> SessionWorktree:
    return SessionWorktree(
        id=row["id"],
        session_id=row["session_id"],
        repo_root=row["repo_root"],
        worktree_path=row["worktree_path"],
        branch_name=row["branch_name"],
        base_ref=row["base_ref"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


_SELECT_COLUMNS = (
    "id, session_id, repo_root, worktree_path, branch_name, "
    "base_ref, status, created_at, updated_at"
)


def register_session_worktree(
    conn: sqlite3.Connection,
    session_id: str,
    repo_root: str,
    worktree_path: str,
    branch_name: Optional[str],
    base_ref: str = "HEAD",
    now_ms: Optional[int] = None,
) -> SessionWorktree:
    """登记一个会话 worktree。同路径重复登记幂等（返回已有行）。"""
    stamp = _now_ms(now_ms)
    existing = get_worktree_by_path(conn, worktree_path)
    if existing is not None:
        return existing
    row_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO session_worktrees (
            id, session_id, repo_root, worktree_path, branch_name,
            base_ref, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row_id,
            session_id,
            repo_root,
            worktree_path,
            branch_name,
            base_ref,
            STATUS_ACTIVE,
            stamp,
            stamp,
        ),
    )
    conn.commit()
    created = get_worktree_by_path(conn, worktree_path)
    assert created is not None
    return created


def get_worktree_by_path(
    conn: sqlite3.Connection, worktree_path: str
) -> Optional[SessionWorktree]:
    row = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM session_worktrees WHERE worktree_path = ?",
        (worktree_path,),
    ).fetchone()
    return None if row is None else _row_to_worktree(row)


def list_session_worktrees(
    conn: sqlite3.Connection,
    session_id: Optional[str] = None,
    repo_root: Optional[str] = None,
    status: Optional[str] = None,
) -> List[SessionWorktree]:
    """按会话/仓库/状态过滤列出 worktree，创建时间倒序。"""
    clauses: List[str] = []
    params: List[str] = []
    if session_id is not None:
        clauses.append("session_id = ?")
        params.append(session_id)
    if repo_root is not None:
        clauses.append("repo_root = ?")
        params.append(repo_root)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    sql = f"SELECT {_SELECT_COLUMNS} FROM session_worktrees"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_worktree(r) for r in rows]


def update_worktree_status(
    conn: sqlite3.Connection,
    worktree_id: str,
    status: str,
    now_ms: Optional[int] = None,
) -> Optional[SessionWorktree]:
    """流转 status（active → merged/discarded）；行不存在返回 None。"""
    if status not in _VALID_STATUSES:
        raise ValueError(f"非法 worktree 状态: {status!r}")
    cursor = conn.execute(
        "UPDATE session_worktrees SET status = ?, updated_at = ? WHERE id = ?",
        (status, _now_ms(now_ms), worktree_id),
    )
    conn.commit()
    if cursor.rowcount == 0:
        return None
    row = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM session_worktrees WHERE id = ?",
        (worktree_id,),
    ).fetchone()
    return None if row is None else _row_to_worktree(row)


def delete_session_worktree(
    conn: sqlite3.Connection, worktree_id: str
) -> bool:
    """物理删除登记行（磁盘清理完成后调用）。返回是否删掉了行。"""
    cursor = conn.execute(
        "DELETE FROM session_worktrees WHERE id = ?", (worktree_id,)
    )
    conn.commit()
    return cursor.rowcount > 0
