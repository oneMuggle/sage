# ruff: noqa: UP006, UP007, UP035 — Python 3.8 typing compatibility
"""R187 data repository contract tests for SessionTodoRepository and artifact_version_repo."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.data import artifact_version_repo
from backend.data.artifact_version_repo import (
    MAX_TEXT_BYTES,
    ConflictError,
    apply_edit,
    create_version,
    get_latest_version,
    get_version,
    list_versions,
)
from backend.data.database import Database
from backend.data.session_todo_repo import SessionTodoRepository

pytestmark = pytest.mark.unit


@pytest.fixture()
def isolated_db(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "todo_ver_r187.db"))
    db.init_db()
    with patch("backend.data.session_todo_repo.get_database", return_value=db), patch(
        "backend.data.artifact_version_repo.get_database", return_value=db
    ):
        yield db, tmp_path


def test_session_todo_repo_upsert_corrupt_json_and_delete(isolated_db) -> None:
    db, _ = isolated_db
    repo = SessionTodoRepository()
    assert repo.get("s-empty") is None

    todos_v1 = [{"id": "1", "content": "step 1", "status": "in_progress"}]
    repo.upsert("s-1", todos_v1)
    assert repo.get("s-1") == todos_v1

    todos_v2 = [{"id": "1", "content": "step 1", "status": "completed"}]
    repo.upsert("s-1", todos_v2)
    assert repo.get("s-1") == todos_v2

    # Corrupt JSON or non-list JSON degrades gracefully to None
    conn = db.get_connection()
    conn.execute("UPDATE session_todos SET todos_json = '{bad json' WHERE session_id = 's-1'")
    conn.commit()
    assert repo.get("s-1") is None

    conn.execute("UPDATE session_todos SET todos_json = ? WHERE session_id = ?", ('{"not": "a list"}', "s-1"))
    conn.commit()
    assert repo.get("s-1") is None

    repo.delete("s-1")
    assert repo.get("s-1") is None


@pytest.mark.asyncio()
async def test_artifact_version_create_cap_and_crlf_apply_edit(isolated_db) -> None:
    db, tmp_path = isolated_db
    conn = db.get_connection()
    conn.execute("INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)", ("s-1", "t", 1, 1))
    for aid in ("art-1", "art-crlf"):
        conn.execute(
            "INSERT INTO artifacts (id, session_id, name, path, kind, size, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (aid, "s-1", f"{aid}.md", str(tmp_path / f"{aid}.md"), "markdown", 10, 1_000),
        )
    conn.commit()
    snap_dir = str(tmp_path / "snaps")

    v1 = create_version("art-1", "hello\nworld", "hash-1", snap_dir, note="init")
    assert v1["version_num"] == 1
    assert get_version("art-1", 1)["content"] == "hello\nworld"
    assert get_latest_version("art-1")["version_num"] == 1
    assert len(list_versions("art-1")) == 1

    # Cap enforcement when version exceeds MAX_VERSIONS_PER_ARTIFACT
    with patch.object(artifact_version_repo, "MAX_VERSIONS_PER_ARTIFACT", 1), pytest.raises(
        ValueError, match="已达最大版本数"
    ):
        create_version("art-1", "v2", "hash-2", snap_dir)

    # apply_edit supports CRLF file matched against LF-normalized base_hash
    target = tmp_path / "doc.md"
    target.write_bytes(b"line1\r\nline2\r\n")
    lf_hash = hashlib.sha256(b"line1\nline2\n").hexdigest()

    edited = await apply_edit(
        artifact_id="art-crlf",
        artifact_path=str(target),
        base_hash=lf_hash,
        new_content="line1\nline2\nline3\n",
        note="added line3",
    )
    assert edited["version_num"] == 1
    assert target.read_text(encoding="utf-8") == "line1\nline2\nline3\n"

    # Mismatched base_hash raises ConflictError
    with pytest.raises(ConflictError):
        await apply_edit(
            artifact_id="art-crlf",
            artifact_path=str(target),
            base_hash="0" * 64,
            new_content="override",
        )

    # Oversized payload raises ValueError before touching disk
    with pytest.raises(ValueError, match="超过上限"):
        await apply_edit(
            artifact_id="art-crlf",
            artifact_path=str(target),
            base_hash=edited["content_hash"],
            new_content="x" * (MAX_TEXT_BYTES + 10),
        )
