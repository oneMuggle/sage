"""会话级 worktree 路由测试（worktree 模式 P1，2026-09-18）。

不起 HTTP server，直接调用路由函数（与 workspace_routes 测试同风格）：
- new → open 幂等重绑、merge 合回主仓、外部删除后启动对账 sweep。
真实 git 仓库用 tmp_path 构造；DB 用 Database(":memory:")。
"""

import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from backend.api import worktree_routes as wr
from backend.data import database as db_mod
from backend.office.session_workspace import bind_session_workspace


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True
    )


@pytest.fixture()
def conn(tmp_path: Path):
    db = db_mod.Database(db_path=":memory:")
    db.init_db()
    c = db.get_connection()
    now = int(time.time() * 1000)
    c.execute(
        "INSERT INTO sessions (id, created_at, updated_at) VALUES (?, ?, ?)",
        ("s1", now, now),
    )
    c.commit()
    original = wr._connection
    wr._connection = lambda: c  # type: ignore[assignment]
    yield c
    wr._connection = original  # type: ignore[assignment]
    c.close()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "tester")
    (r / "f.txt").write_text("x")
    _git(r, "add", ".")
    _git(r, "commit", "-m", "init")
    return r


def _branches(c: sqlite3.Connection, name: str) -> list:
    rows = c.execute(
        "SELECT branch_name, status FROM session_worktrees WHERE session_id = ?",
        (name,),
    ).fetchall()
    return [(row["branch_name"], row["status"]) for row in rows]


def test_new_worktree_creates_binds_and_merges(conn: sqlite3.Connection, repo: Path):
    bind_session_workspace(conn, "s1", str(repo))

    r = wr.create_or_switch(
        "s1", wr.WorktreeCreateRequest(mode="new", branch="feat/a", base_ref="HEAD")
    )
    assert r.ok and r.workspace_path
    wt_path = Path(r.workspace_path)
    assert (wt_path / "f.txt").is_file()
    assert _branches(conn, "s1")[0] == ("feat/a", "active")

    # 同分支再次 new → 幂等重绑到既有目录
    r2 = wr.create_or_switch(
        "s1", wr.WorktreeCreateRequest(mode="new", branch="feat/a", base_ref="HEAD")
    )
    assert r2.ok and r2.workspace_path == str(wt_path)

    # worktree 内提交 → merge 合回主仓
    (wt_path / "new.txt").write_text("hello")
    _git(wt_path, "add", ".")
    _git(wt_path, "commit", "-m", "work")
    m = wr.merge_worktree("s1", wr.WorktreeMergeRequest(worktree_id=r.worktree.id))
    assert m.result["ok"] and m.result["code"] == "merged"
    assert (repo / "new.txt").is_file()
    assert _branches(conn, "s1")[0][1] == "merged"


def test_checkout_mode_rejects_dirty_workspace(conn: sqlite3.Connection, repo: Path):
    from fastapi import HTTPException

    bind_session_workspace(conn, "s1", str(repo))
    _git(repo, "branch", "side")
    (repo / "dirty.txt").write_text("d")
    with pytest.raises(HTTPException) as exc:
        wr.create_or_switch(
            "s1", wr.WorktreeCreateRequest(mode="checkout", branch="side")
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "workspace_dirty"


def test_sweep_marks_deleted_worktrees_and_rebinds(
    conn: sqlite3.Connection, repo: Path
):
    bind_session_workspace(conn, "s1", str(repo))
    r = wr.create_or_switch(
        "s1", wr.WorktreeCreateRequest(mode="new", branch="feat/gone", base_ref="HEAD")
    )
    wt_path = Path(r.workspace_path)
    assert wt_path.is_dir()

    # 用户外部手动删目录（worktree remove 未走）→ 对账应标 discarded
    _git(repo, "worktree", "remove", "--force", str(wt_path))

    swept = wr.sweep_registered_worktrees(conn)
    assert swept == 1
    assert _branches(conn, "s1")[0] == ("feat/gone", "discarded")
    # 会话绑定从死路径退回主仓
    assert repo.is_dir()


def test_invalid_branch_rejected(conn: sqlite3.Connection, repo: Path):
    from fastapi import HTTPException

    bind_session_workspace(conn, "s1", str(repo))
    with pytest.raises(HTTPException) as exc:
        wr.create_or_switch(
            "s1", wr.WorktreeCreateRequest(mode="new", branch="--upload")
        )
    assert exc.value.status_code == 422
