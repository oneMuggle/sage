# ruff: noqa: UP006, UP007, UP035
"""Tests for duplicate-group listing (Phase 1 Item A: 重复清理).

Covers:

- ``storage.list_duplicate_groups`` — groups live documents by stored
  content digest, only returning groups with two or more members;
- ``GET /documents/duplicate-groups`` — route wrapper returning typed
  groups in newest-first order.

Documents without a digest, archived documents, and singleton digests are
intentionally excluded: the UI only offers cleanup for real duplicates.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.api import office_dedup_routes
from backend.api.office_dedup_routes import list_duplicate_groups_endpoint
from backend.office.storage import (
    ensure_content_hash_table,
    list_duplicate_groups,
)

NOW_MS = 1_700_000_000_000


class _FakeDatabase:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_connection(self) -> sqlite3.Connection:
        return self._conn


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def conn(monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE office_documents (
            id TEXT PRIMARY KEY,
            workspace_path TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            original_filename TEXT,
            generated_filename TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            metadata TEXT,
            derived_from TEXT,
            archived_at INTEGER,
            active_spec_id TEXT
        )
        """
    )
    ensure_content_hash_table(connection)
    monkeypatch.setattr(
        office_dedup_routes, "get_database", lambda: _FakeDatabase(connection)
    )
    return connection


def _insert_doc(
    conn: sqlite3.Connection,
    workspace: Path,
    doc_id: str,
    *,
    created_at: int = NOW_MS,
    archived_at: int | None = None,
    content_hash: str | None = None,
) -> None:
    canonical = str(workspace.resolve())
    conn.execute(
        """
        INSERT INTO office_documents
            (id, workspace_path, doc_type, original_filename,
             generated_filename, status, created_at, updated_at,
             metadata, derived_from, archived_at, active_spec_id)
        VALUES (?, ?, 'word', ?, ?, 'parsed', ?, ?, ?, NULL, ?, NULL)
        """,
        (
            doc_id,
            canonical,
            f"{doc_id}.docx",
            f"{doc_id}.docx",
            created_at,
            created_at,
            '{"file_size_bytes": 12}',
            archived_at,
        ),
    )
    if content_hash is not None:
        conn.execute(
            """
            INSERT INTO office_document_hashes
                (id, workspace_path, content_hash, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (doc_id, canonical, content_hash, created_at),
        )
    conn.commit()


# ──────────────────────────────────────────────────────────────────────
# storage.list_duplicate_groups
# ──────────────────────────────────────────────────────────────────────


def test_groups_only_include_real_duplicates(
    conn: sqlite3.Connection, workspace: Path
) -> None:
    _insert_doc(conn, workspace, "a1", content_hash="sha256:aaa", created_at=100)
    _insert_doc(conn, workspace, "a2", content_hash="sha256:aaa", created_at=200)
    _insert_doc(conn, workspace, "b1", content_hash="sha256:bbb", created_at=300)

    groups = list_duplicate_groups(conn, str(workspace.resolve()))
    assert len(groups) == 1
    digest, docs = groups[0]
    assert digest == "sha256:aaa"
    assert {d.id for d in docs} == {"a1", "a2"}


def test_groups_exclude_documents_without_hash(
    conn: sqlite3.Connection, workspace: Path
) -> None:
    _insert_doc(conn, workspace, "a1", content_hash="sha256:aaa")
    _insert_doc(conn, workspace, "no-hash-1")
    _insert_doc(conn, workspace, "no-hash-2")

    assert list_duplicate_groups(conn, str(workspace.resolve())) == []


def test_groups_exclude_archived_documents(
    conn: sqlite3.Connection, workspace: Path
) -> None:
    _insert_doc(conn, workspace, "live", content_hash="sha256:aaa", created_at=100)
    _insert_doc(
        conn,
        workspace,
        "archived",
        content_hash="sha256:aaa",
        created_at=200,
        archived_at=9999,
    )

    # Only one live member remains → not a duplicate group.
    assert list_duplicate_groups(conn, str(workspace.resolve())) == []


def test_groups_ordered_newest_first(
    conn: sqlite3.Connection, workspace: Path
) -> None:
    _insert_doc(conn, workspace, "old-1", content_hash="sha256:old", created_at=100)
    _insert_doc(conn, workspace, "old-2", content_hash="sha256:old", created_at=150)
    _insert_doc(conn, workspace, "new-1", content_hash="sha256:new", created_at=500)
    _insert_doc(conn, workspace, "new-2", content_hash="sha256:new", created_at=600)

    groups = list_duplicate_groups(conn, str(workspace.resolve()))
    assert [digest for digest, _ in groups] == ["sha256:new", "sha256:old"]


def test_group_members_newest_first(
    conn: sqlite3.Connection, workspace: Path
) -> None:
    _insert_doc(conn, workspace, "old", content_hash="sha256:aaa", created_at=100)
    _insert_doc(conn, workspace, "new", content_hash="sha256:aaa", created_at=300)
    _insert_doc(conn, workspace, "mid", content_hash="sha256:aaa", created_at=200)

    _, docs = list_duplicate_groups(conn, str(workspace.resolve()))[0]
    assert [d.id for d in docs] == ["new", "mid", "old"]


def test_groups_scoped_to_workspace(
    conn: sqlite3.Connection, workspace: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    _insert_doc(conn, workspace, "here-1", content_hash="sha256:aaa")
    _insert_doc(conn, workspace, "here-2", content_hash="sha256:aaa")
    _insert_doc(conn, other, "there-1", content_hash="sha256:aaa")

    groups = list_duplicate_groups(conn, str(workspace.resolve()))
    assert len(groups) == 1
    assert {d.id for d in groups[0][1]} == {"here-1", "here-2"}


# ──────────────────────────────────────────────────────────────────────
# Route
# ──────────────────────────────────────────────────────────────────────


def test_endpoint_returns_groups(
    conn: sqlite3.Connection, workspace: Path
) -> None:
    _insert_doc(conn, workspace, "a1", content_hash="sha256:aaa", created_at=100)
    _insert_doc(conn, workspace, "a2", content_hash="sha256:aaa", created_at=200)

    response = list_duplicate_groups_endpoint(str(workspace))
    assert response.total == 1
    assert response.groups[0].content_hash == "sha256:aaa"
    assert [d.id for d in response.groups[0].documents] == ["a2", "a1"]


def test_endpoint_empty_when_no_duplicates(
    conn: sqlite3.Connection, workspace: Path
) -> None:
    _insert_doc(conn, workspace, "only", content_hash="sha256:aaa")

    response = list_duplicate_groups_endpoint(str(workspace))
    assert response.total == 0
    assert response.groups == []
