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


@pytest.fixture()
def bound_non_git_session(
    conn: sqlite3.Connection, session_id: str, tmp_path: Path
) -> str:
    plain = tmp_path / "plain-workspace"
    plain.mkdir()
    bind_session_workspace(conn, session_id, str(plain))
    return session_id


@pytest.mark.asyncio()
async def test_changes_non_git_workspace_returns_empty_state(
    client: httpx.AsyncClient, bound_non_git_session: str
) -> None:
    """非 git 工作区不是错误：返回 200 空态 + is_git_repo=False。"""
    response = await client.get(
        f"/api/v1/sessions/{bound_non_git_session}/workspace/changes"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_git_repo"] is False
    assert body["changes"] == []
    assert body["clean"] is True


@pytest.mark.asyncio()
async def test_diff_non_git_workspace_returns_409(
    client: httpx.AsyncClient, bound_non_git_session: str
) -> None:
    response = await client.get(
        f"/api/v1/sessions/{bound_non_git_session}/workspace/changes/diff",
        params={"path": "a.py"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_a_git_repo"


@pytest.mark.asyncio()
async def test_changes_git_binary_missing_is_502(
    client: httpx.AsyncClient,
    bound_session: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """git 缺失是环境错误（502），不能误报成「不是 Git 仓库」空态。"""
    from backend.tools import git_tool

    monkeypatch.setattr(git_tool, "GIT_BINARY", "definitely-not-git-xyz")
    response = await client.get(f"/api/v1/sessions/{bound_session}/workspace/changes")
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "git_error"


@pytest.mark.asyncio()
async def test_changes_rename_numstat_maps_new_path(
    client: httpx.AsyncClient, bound_session: str, git_workspace: Path
) -> None:
    """同目录 rename 的 numstat 需映射回新路径，+/- 徽章才不丢。"""
    src = git_workspace / "tracked.py"
    subprocess.run(["git", "mv", "tracked.py", "renamed.py"], cwd=git_workspace, check=True, capture_output=True)
    (git_workspace / "renamed.py").write_text("print('v2 renamed')\n", encoding="utf-8")
    assert not src.exists()

    body = (
        await client.get(f"/api/v1/sessions/{bound_session}/workspace/changes")
    ).json()
    renamed = next(e for e in body["changes"] if e["path"] == "renamed.py")
    assert renamed["insertions"] is not None
    assert renamed["old_path"] == "tracked.py"


@pytest.fixture()
def subdir_repo(tmp_path: Path):
    """仓库根下有一个工作区子目录 pkg/，同时存在工作区外的改动。"""
    repo = tmp_path / "repo"
    sub = repo / "pkg"
    sub.mkdir(parents=True)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init")
    git("config", "user.email", "test@sage.local")
    git("config", "user.name", "Sage Test")
    (repo / "outside.txt").write_text("v1\n", encoding="utf-8")
    (sub / "inside.py").write_text("v1\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "init")
    (repo / "outside.txt").write_text("v2\n", encoding="utf-8")
    (sub / "inside.py").write_text("v2\n", encoding="utf-8")
    (sub / "new.txt").write_text("n\n", encoding="utf-8")
    return repo, sub


@pytest.mark.asyncio()
async def test_changes_subdir_workspace_is_workspace_relative(
    client: httpx.AsyncClient,
    conn: sqlite3.Connection,
    session_id: str,
    subdir_repo,
) -> None:
    """工作区是仓库子目录时：只列工作区内文件，路径相对工作区，徽章可用。"""
    _repo, sub = subdir_repo
    bind_session_workspace(conn, session_id, str(sub))

    body = (
        await client.get(f"/api/v1/sessions/{session_id}/workspace/changes")
    ).json()
    entries = {entry["path"]: entry for entry in body["changes"]}
    assert set(entries) == {"inside.py", "new.txt"}
    assert entries["inside.py"]["insertions"] == 1
    assert entries["new.txt"]["insertions"] == 1
    assert body["clean"] is False

    diff = await client.get(
        f"/api/v1/sessions/{session_id}/workspace/changes/diff",
        params={"path": "inside.py"},
    )
    assert diff.status_code == 200
    assert "+v2" in diff.json()["diff"]

    preview = await client.get(
        f"/api/v1/sessions/{session_id}/workspace/changes/file",
        params={"path": "inside.py"},
    )
    assert preview.status_code == 200
    assert preview.json()["content"] == "v2\n"


@pytest.mark.asyncio()
async def test_changes_unicode_untracked_path_roundtrip(
    client: httpx.AsyncClient, bound_session: str, git_workspace: Path
) -> None:
    """中文未跟踪文件：列表原文、diff 与预览均可用（porcelain -z 回归）。"""
    (git_workspace / "02_编制说明.txt").write_text("内容\n", encoding="utf-8")

    body = (
        await client.get(f"/api/v1/sessions/{bound_session}/workspace/changes")
    ).json()
    assert "02_编制说明.txt" in {entry["path"] for entry in body["changes"]}

    diff = await client.get(
        f"/api/v1/sessions/{bound_session}/workspace/changes/diff",
        params={"path": "02_编制说明.txt"},
    )
    assert diff.status_code == 200
    assert "+内容" in diff.json()["diff"]

    file_response = await client.get(
        f"/api/v1/sessions/{bound_session}/workspace/changes/file",
        params={"path": "02_编制说明.txt"},
    )
    assert file_response.status_code == 200
    assert file_response.json()["content"] == "内容\n"


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


# right-panel R5: 每文件 +/- 行数（numstat / 未跟踪文件行数统计）
@pytest.mark.asyncio()
async def test_changes_includes_numstat(
    client: httpx.AsyncClient, bound_session: str
) -> None:
    response = await client.get(f"/api/v1/sessions/{bound_session}/workspace/changes")
    assert response.status_code == 200
    body = response.json()
    tracked = next(e for e in body["changes"] if e["path"] == "tracked.py")
    untracked = next(e for e in body["changes"] if e["path"] == "untracked.py")
    # v1 → v2 单行替换：+1/−1（numstat 口径）
    assert tracked["insertions"] == 1
    assert tracked["deletions"] == 1
    # 未跟踪文件退化为行数统计（"print('new')\n" = 1 行），deletions 恒 0
    assert untracked["insertions"] == 1
    assert untracked["deletions"] == 0


@pytest.mark.asyncio()
async def test_changes_numstat_binary_file_is_none(
    client: httpx.AsyncClient, conn: sqlite3.Connection, session_id: str, tmp_path: Path
) -> None:
    repo = tmp_path / "binws"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init")
    git("config", "user.email", "test@sage.local")
    git("config", "user.name", "Sage Test")
    (repo / "logo.bin").write_bytes(b"\x00\x01\x02binary")
    git("add", ".")
    git("commit", "-m", "init")
    (repo / "logo.bin").write_bytes(b"\x00\x99changed")
    bind_session_workspace(conn, session_id, str(repo))

    response = await client.get(f"/api/v1/sessions/{session_id}/workspace/changes")
    assert response.status_code == 200
    entry = next(e for e in response.json()["changes"] if e["path"] == "logo.bin")
    assert entry["insertions"] is None
    assert entry["deletions"] is None


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


# right-panel R5: 未跟踪文件的 "new file" 全加号 diff
@pytest.mark.asyncio()
async def test_diff_untracked_file_renders_new_file_diff(
    client: httpx.AsyncClient, bound_session: str
) -> None:
    response = await client.get(
        f"/api/v1/sessions/{bound_session}/workspace/changes/diff",
        params={"path": "untracked.py"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is False
    assert "new file mode 100644" in body["diff"]
    assert "--- /dev/null" in body["diff"]
    assert "+print('new')" in body["diff"]


@pytest.mark.asyncio()
async def test_diff_tracked_unchanged_file_stays_empty(
    client: httpx.AsyncClient, conn: sqlite3.Connection, session_id: str, tmp_path: Path
) -> None:
    """未变更的已跟踪文件不误触 new-file 回退，diff 维持空串。"""
    repo = tmp_path / "cleantracked"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init")
    git("config", "user.email", "test@sage.local")
    git("config", "user.name", "Sage Test")
    (repo / "same.py").write_text("print('same')\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "init")
    bind_session_workspace(conn, session_id, str(repo))

    response = await client.get(
        f"/api/v1/sessions/{session_id}/workspace/changes/diff",
        params={"path": "same.py"},
    )
    assert response.status_code == 200
    assert response.json()["diff"] == ""


# ============================================================================
# right-panel R6: 变更面板"预览"视图（GET /changes/file 文件内容只读）
# ============================================================================


@pytest.mark.asyncio()
async def test_file_preview_returns_content(
    client: httpx.AsyncClient, bound_session: str, git_workspace: Path
) -> None:
    response = await client.get(
        f"/api/v1/sessions/{bound_session}/workspace/changes/file",
        params={"path": "tracked.py"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "tracked.py"
    # 接口返回原始文件字节（Windows 夹具落盘为 CRLF,归一化后断言）
    assert body["content"].replace("\r\n", "\n") == "print('v2')\n"
    assert body["truncated"] is False


@pytest.mark.asyncio()
async def test_file_preview_rejects_path_traversal(
    client: httpx.AsyncClient, bound_session: str
) -> None:
    response = await client.get(
        f"/api/v1/sessions/{bound_session}/workspace/changes/file",
        params={"path": "../outside.py"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "path_outside_workspace"


@pytest.mark.asyncio()
async def test_file_preview_missing_file_is_404(
    client: httpx.AsyncClient, bound_session: str
) -> None:
    response = await client.get(
        f"/api/v1/sessions/{bound_session}/workspace/changes/file",
        params={"path": "nope.py"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "file_not_found"


@pytest.mark.asyncio()
async def test_file_preview_binary_file_is_415(
    client: httpx.AsyncClient, bound_session: str, git_workspace: Path
) -> None:
    (git_workspace / "logo.bin").write_bytes(b"\x00\x01\x02binary")
    response = await client.get(
        f"/api/v1/sessions/{bound_session}/workspace/changes/file",
        params={"path": "logo.bin"},
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "binary_file"


@pytest.mark.asyncio()
async def test_file_preview_truncates_large_content(
    client: httpx.AsyncClient, conn: sqlite3.Connection, session_id: str, tmp_path: Path
) -> None:
    """超 512KiB 的文本内容截断并置 truncated=true。"""
    repo = tmp_path / "bigws"
    repo.mkdir()
    repo.mkdir(exist_ok=True)
    big = "x" * 1024 + "\n"
    (repo / "big.txt").write_text(big * 600, encoding="utf-8")  # ~614KiB
    bind_session_workspace(conn, session_id, str(repo))

    response = await client.get(
        f"/api/v1/sessions/{session_id}/workspace/changes/file",
        params={"path": "big.txt"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is True
    assert len(body["content"]) < len(big) * 600


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
