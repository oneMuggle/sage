# ruff: noqa: UP006, UP007, UP035
"""Route-level tests for GET /office/documents search/filter/sort (Item A).

Verifies the endpoint forwards ``q`` / ``doc_type`` / ``sort`` to
``storage.list_documents`` and canonicalizes the workspace path. The
storage-level behavior is covered in
``backend/tests/unit/office/test_list_documents_search_filter_sort.py``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.api import office_routes
from backend.api.office_routes import list_documents_endpoint
from backend.office.models import OfficeDocType


class _FakeDatabase:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_connection(self) -> sqlite3.Connection:
        return self._connection


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def conn(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> sqlite3.Connection:
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
    connection.commit()
    monkeypatch.setattr(
        office_routes, "_db", lambda: _FakeDatabase(connection)
    )
    return connection


def _insert(
    conn: sqlite3.Connection,
    workspace: Path,
    doc_id: str,
    *,
    doc_type: str = "word",
    original_filename: str | None = None,
    generated_filename: str | None = None,
    created_at: int = 1000,
    updated_at: int = 1000,
    file_size_bytes: int = 1024,
) -> None:
    conn.execute(
        """
        INSERT INTO office_documents
            (id, workspace_path, doc_type, original_filename,
             generated_filename, status, created_at, updated_at,
             metadata, derived_from, archived_at, active_spec_id)
        VALUES (?, ?, ?, ?, ?, 'parsed', ?, ?, ?, NULL, NULL, NULL)
        """,
        (
            doc_id,
            str(workspace.resolve()),
            doc_type,
            original_filename,
            generated_filename or f"{doc_id}.docx",
            created_at,
            updated_at,
            json.dumps({"file_size_bytes": file_size_bytes}),
        ),
    )
    conn.commit()


def test_endpoint_forwards_q(conn: sqlite3.Connection, workspace: Path) -> None:
    _insert(conn, workspace, "a", original_filename="季度报告.docx")
    _insert(conn, workspace, "b", original_filename="月度总结.docx")

    response = list_documents_endpoint(str(workspace), q="季度")
    assert response.total == 1
    assert response.documents[0].id == "a"


def test_endpoint_forwards_doc_type(
    conn: sqlite3.Connection, workspace: Path
) -> None:
    _insert(conn, workspace, "w", doc_type="word")
    _insert(conn, workspace, "x", doc_type="excel")

    response = list_documents_endpoint(str(workspace), doc_type=OfficeDocType.EXCEL)
    assert response.total == 1
    assert response.documents[0].id == "x"


def test_endpoint_forwards_sort(conn: sqlite3.Connection, workspace: Path) -> None:
    _insert(conn, workspace, "old", original_filename="old.docx", created_at=100)
    _insert(conn, workspace, "new", original_filename="new.docx", created_at=200)

    response = list_documents_endpoint(str(workspace), sort="created_at")
    assert [d.id for d in response.documents] == ["old", "new"]

    response_desc = list_documents_endpoint(str(workspace), sort="-created_at")
    assert [d.id for d in response_desc.documents] == ["new", "old"]


def test_endpoint_combines_filters(
    conn: sqlite3.Connection, workspace: Path
) -> None:
    _insert(
        conn,
        workspace,
        "word-report",
        doc_type="word",
        original_filename="report-a.docx",
        updated_at=100,
    )
    _insert(
        conn,
        workspace,
        "word-report-new",
        doc_type="word",
        original_filename="report-b.docx",
        updated_at=300,
    )
    _insert(
        conn,
        workspace,
        "excel-report",
        doc_type="excel",
        original_filename="report-c.xlsx",
        updated_at=200,
    )

    response = list_documents_endpoint(
        str(workspace),
        q="report",
        doc_type=OfficeDocType.WORD,
        sort="-updated_at",
    )
    assert [d.id for d in response.documents] == [
        "word-report-new",
        "word-report",
    ]


def test_endpoint_default_behavior_unchanged(
    conn: sqlite3.Connection, workspace: Path
) -> None:
    _insert(conn, workspace, "a", created_at=100)
    _insert(conn, workspace, "b", created_at=200)

    response = list_documents_endpoint(str(workspace))
    # Default order: created_at DESC
    assert [d.id for d in response.documents] == ["b", "a"]
