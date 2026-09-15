# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""U1 变更面板数据源（GET /sessions/{id}/workspace/changes[/diff]）集成测试。

沿用 test_workspace_routes.py 的 fixture 模式（内存 DB + ASGITransport），
workspace 用真实临时 git 仓库（git 跨平台可用，与 test_git_tool.py 同口径）。
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from backend.data import database as database_module
from backend.data.database import Database
from backend.main import app
from backend.office.session_workspace import bind_session_workspace


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return test_db


@pytest.fixture()
def conn(db: Database) -> sqlite3.Connection:
    return db.get_connection()


@pytest.fixture()
def session_id(conn: sqlite3.Connection) -> str:
    value = "session-changes"
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (value, "Changes", 1, 1),
    )
    conn.commit()
    return value


@pytest.fixture()
def git_workspace(tmp_path: Path) -> Path:
    """带一个已跟踪文件（已修改）+ 一个未跟踪文件的 git 仓库。"""
    path = tmp_path / "workspace"
    path.mkdir()
    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=path, check=True, capture_output=True
        )
    git("init")
    git("config", "user.email", "test@sage.local")
    git("config", "user.name", "Sage Test")
    (path / "tracked.py").write_text("print('v1')\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "init")
    (path / "tracked.py").write_text("print('v2')\n", encoding="utf-8")
    (path / "untracked.py").write_text("print('new')\n", encoding="utf-8")
    return path


@pytest_asyncio.fixture()
async def client(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as value:
        yield value


@pytest.fixture()
def bound_session(
    conn: sqlite3.Connection, session_id: str, git_workspace: Path
) -> str:
    bind_session_workspace(conn, session_id, str(git_workspace))
    return session_id


@pytest.mark.asyncio()
async def test_changes_requires_existing_session(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/sessions/nope/workspace/changes")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "session_not_found"


@pytest.mark.asyncio()
async def test_changes_requires_bound_workspace(
    client: httpx.AsyncClient, session_id: str
) -> None:
    response = await client.get(f"/api/v1/sessions/{session_id}/workspace/changes")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "workspace_not_bound"


@pytest.mark.asyncio()
async def test_changes_lists_modified_and_untracked(
    client: httpx.AsyncClient, bound_session: str
) -> None:
    response = await client.get(f"/api/v1/sessions/{bound_session}/workspace/changes")
    assert response.status_code == 200
    body = response.json()
    assert body["clean"] is False
    paths = {entry["path"] for entry in body["changes"]}
    assert "tracked.py" in paths
    assert "untracked.py" in paths
    tracked = next(e for e in body["changes"] if e["path"] == "tracked.py")
    assert tracked["worktree_status"] == "M"
    assert isinstance(body["branch"], str)


@pytest.mark.asyncio()
async def test_changes_clean_repo_has_empty_list(
    client: httpx.AsyncClient, conn: sqlite3.Connection, session_id: str, tmp_path: Path
) -> None:
    repo = tmp_path / "clean"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    bind_session_workspace(conn, session_id, str(repo))
    response = await client.get(f"/api/v1/sessions/{session_id}/workspace/changes")
    assert response.status_code == 200
    body = response.json()
    assert body["clean"] is True
    assert body["changes"] == []


@pytest.mark.asyncio()
async def test_diff_returns_file_diff(
    client: httpx.AsyncClient, bound_session: str
) -> None:
    response = await client.get(
        f"/api/v1/sessions/{bound_session}/workspace/changes/diff",
        params={"path": "tracked.py"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is False
    assert "-print('v1')" in body["diff"]
    assert "+print('v2')" in body["diff"]


@pytest.mark.asyncio()
async def test_diff_path_outside_repo_rejected(
    client: httpx.AsyncClient, bound_session: str, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("x", encoding="utf-8")
    response = await client.get(
        f"/api/v1/sessions/{bound_session}/workspace/changes/diff",
        params={"path": str(outside)},
    )
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "git_error"


@pytest.mark.asyncio()
async def test_diff_without_binding_is_forbidden(
    client: httpx.AsyncClient, session_id: str
) -> None:
    response = await client.get(
        f"/api/v1/sessions/{session_id}/workspace/changes/diff",
        params={"path": "a.py"},
    )
    assert response.status_code == 403
