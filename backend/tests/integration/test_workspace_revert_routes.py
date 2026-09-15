# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""U19 逐文件/逐 hunk 撤销端点集成测试（POST /sessions/{id}/workspace/changes/revert[-hunks]）。

沿用 test_workspace_changes_routes.py 的 fixture 模式（内存 DB + ASGITransport
+ 真实临时 git 仓库）。
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
    value = "session-revert"
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (value, "Revert", 1, 1),
    )
    conn.commit()
    return value


@pytest.fixture()
def git_workspace(tmp_path: Path) -> Path:
    """已跟踪文件 v1 提交 + 工作区两处远离的修改 + 一个未跟踪文件。

    两处编辑相距 > 2×上下文（3 行），保证 git diff 产出两个独立 hunk。
    """
    path = tmp_path / "workspace"
    path.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)

    git("init")
    git("config", "user.email", "test@sage.local")
    git("config", "user.name", "Sage Test")
    lines = [f"l{i}" for i in range(1, 21)]
    (path / "app.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "init")
    edited = list(lines)
    edited[1] = "l2-EDIT"
    edited[17] = "l18-EDIT"
    (path / "app.py").write_text("\n".join(edited) + "\n", encoding="utf-8")
    (path / "untracked.py").write_text("print('new')\n", encoding="utf-8")
    return path


@pytest_asyncio.fixture()
async def client(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as value:
        yield value


@pytest.fixture()
def bound_session(conn: sqlite3.Connection, session_id: str, git_workspace: Path) -> str:
    bind_session_workspace(conn, session_id, str(git_workspace))
    return session_id


def _worktree(path: Path) -> str:
    return (path / "app.py").read_text(encoding="utf-8")


def _hunk_count(diff_text: str) -> int:
    return sum(1 for line in diff_text.splitlines() if line.startswith("@@ "))


@pytest.mark.asyncio()
async def test_revert_restores_file(
    client: httpx.AsyncClient, bound_session: str, git_workspace: Path
) -> None:
    response = await client.post(
        f"/api/v1/sessions/{bound_session}/workspace/changes/revert",
        json={"paths": ["app.py"]},
    )
    assert response.status_code == 200
    assert response.json()["reverted"] == ["app.py"]
    assert "l2-EDIT" not in _worktree(git_workspace)
    assert "l18-EDIT" not in _worktree(git_workspace)


@pytest.mark.asyncio()
async def test_revert_untracked_requires_flag(
    client: httpx.AsyncClient, bound_session: str, git_workspace: Path
) -> None:
    response = await client.post(
        f"/api/v1/sessions/{bound_session}/workspace/changes/revert",
        json={"paths": ["untracked.py"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reverted"] == []
    assert body["errors"][0]["path"] == "untracked.py"
    assert (git_workspace / "untracked.py").exists()

    response = await client.post(
        f"/api/v1/sessions/{bound_session}/workspace/changes/revert",
        json={"paths": ["untracked.py"], "delete_untracked": True},
    )
    assert response.status_code == 200
    assert response.json()["reverted"] == ["untracked.py"]
    assert not (git_workspace / "untracked.py").exists()


@pytest.mark.asyncio()
async def test_revert_path_escape_rejected(
    client: httpx.AsyncClient, bound_session: str
) -> None:
    response = await client.post(
        f"/api/v1/sessions/{bound_session}/workspace/changes/revert",
        json={"paths": ["../outside.py"]},
    )
    assert response.status_code == 200
    assert response.json()["errors"][0]["error"]


@pytest.mark.asyncio()
async def test_revert_requires_binding(
    client: httpx.AsyncClient, session_id: str
) -> None:
    response = await client.post(
        f"/api/v1/sessions/{session_id}/workspace/changes/revert",
        json={"paths": ["app.py"]},
    )
    assert response.status_code == 403


@pytest.mark.asyncio()
async def test_revert_hunks_restores_only_selected(
    client: httpx.AsyncClient, bound_session: str, git_workspace: Path
) -> None:
    diff = await client.get(
        f"/api/v1/sessions/{bound_session}/workspace/changes/diff",
        params={"path": "app.py"},
    )
    assert _hunk_count(diff.json()["diff"]) == 2

    # 只撤第一个 hunk（l2-EDIT），保留第二个（l18-EDIT）
    response = await client.post(
        f"/api/v1/sessions/{bound_session}/workspace/changes/revert-hunks",
        json={"path": "app.py", "hunk_indices": [0]},
    )
    assert response.status_code == 200
    assert response.json()["reverted_hunks"] == 1
    content = _worktree(git_workspace)
    assert "l2\n" in content
    assert "l18-EDIT" in content


@pytest.mark.asyncio()
async def test_revert_hunks_out_of_range_is_502(
    client: httpx.AsyncClient, bound_session: str, git_workspace: Path
) -> None:
    before = _worktree(git_workspace)
    response = await client.post(
        f"/api/v1/sessions/{bound_session}/workspace/changes/revert-hunks",
        json={"path": "app.py", "hunk_indices": [9]},
    )
    assert response.status_code == 502
    assert _worktree(git_workspace) == before


@pytest.mark.asyncio()
async def test_revert_hunks_requires_binding(
    client: httpx.AsyncClient, session_id: str
) -> None:
    response = await client.post(
        f"/api/v1/sessions/{session_id}/workspace/changes/revert-hunks",
        json={"path": "app.py", "hunk_indices": [0]},
    )
    assert response.status_code == 403
