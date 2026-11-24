"""Tests for ``backend.design.office_sources``.

Covers:
- ``list_office_sources`` filters by doc_type, excludes archived, caps rows
- ``resolve_office_source_path`` rejects unknown ids and unsupported types
- ``resolve_source_input`` enforces exactly-one of file_path / doc_id
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.design.office_sources import (
    OfficeSourceNotFoundError,
    OfficeSourceRef,
    list_office_sources,
    resolve_office_source_path,
    resolve_source_input,
)


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

    from backend.design import office_sources

    monkeypatch.setattr(
        office_sources.DefaultWorkspaceResolver,
        "default_workspace_path",
        lambda self: str(workspace),
    )
    return connection


def _insert(
    conn: sqlite3.Connection,
    workspace: Path,
    doc_id: str,
    *,
    doc_type: str = "word",
    original: str = "src.docx",
    generated: str = "gen.docx",
    created_at: int = 1000,
    updated_at: int = 1000,
    archived: bool = False,
    materialise: bool = True,
) -> None:
    doc_dir = workspace / "office" / doc_type / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    if materialise:
        (doc_dir / generated).write_bytes(b"hello")
    conn.execute(
        """
        INSERT INTO office_documents
            (id, workspace_path, doc_type, original_filename,
             generated_filename, status, created_at, updated_at,
             metadata, derived_from, archived_at, active_spec_id)
        VALUES (?, ?, ?, ?, ?, 'parsed', ?, ?, ?, NULL, ?, NULL)
        """,
        (
            doc_id,
            str(workspace),
            doc_type,
            original,
            generated,
            created_at,
            updated_at,
            '{"file_size_bytes": 5}',
            1 if archived else None,
        ),
    )
    conn.commit()


def test_list_returns_only_word_and_excel(conn, workspace):
    _insert(conn, workspace, "d-word", doc_type="word", original="a.docx")
    _insert(conn, workspace, "d-xl", doc_type="excel", original="b.xlsx")
    _insert(conn, workspace, "d-ppt", doc_type="ppt", original="c.pptx")

    rows = list_office_sources(conn)
    ids = {row.doc_id for row in rows}
    assert ids == {"d-word", "d-xl"}
    assert all(isinstance(row, OfficeSourceRef) for row in rows)


def test_list_filters_by_doc_type(conn, workspace):
    _insert(conn, workspace, "d-word", doc_type="word")
    _insert(conn, workspace, "d-xl", doc_type="excel")

    only_word = list_office_sources(conn, doc_type="word")
    assert [row.doc_id for row in only_word] == ["d-word"]

    unknown = list_office_sources(conn, doc_type="pdf")
    assert unknown == []


def test_list_excludes_archived(conn, workspace):
    _insert(conn, workspace, "d-live", doc_type="word")
    _insert(conn, workspace, "d-archived", doc_type="word", archived=True)

    rows = list_office_sources(conn)
    assert [row.doc_id for row in rows] == ["d-live"]


def test_list_respects_limit(conn, workspace):
    for index in range(5):
        _insert(
            conn,
            workspace,
            f"d-{index}",
            doc_type="word",
            updated_at=1000 + index,
        )

    rows = list_office_sources(conn, limit=2)
    assert len(rows) == 2


def test_resolve_returns_absolute_path(conn, workspace):
    _insert(conn, workspace, "d-ok", doc_type="word", generated="g.docx")

    resolved = resolve_office_source_path(conn, "d-ok")
    assert resolved.is_file()
    assert resolved.name == "g.docx"


def test_resolve_rejects_unknown_id(conn, workspace):
    with pytest.raises(OfficeSourceNotFoundError) as exc_info:
        resolve_office_source_path(conn, "missing")
    assert exc_info.value.reason == "not_found"


def test_resolve_rejects_unsupported_type(conn, workspace):
    _insert(conn, workspace, "d-ppt", doc_type="ppt", generated="c.pptx")

    with pytest.raises(OfficeSourceNotFoundError) as exc_info:
        resolve_office_source_path(conn, "d-ppt")
    assert exc_info.value.reason == "unsupported_type"


def test_resolve_rejects_missing_file_on_disk(conn, workspace):
    _insert(
        conn,
        workspace,
        "d-missing",
        doc_type="word",
        generated="gone.docx",
        materialise=False,
    )

    with pytest.raises(OfficeSourceNotFoundError) as exc_info:
        resolve_office_source_path(conn, "d-missing")
    assert exc_info.value.reason == "file_missing"


def test_resolve_rejects_doc_from_other_workspace(conn, workspace, tmp_path):
    """A doc whose workspace_path differs from the default is invisible."""
    other_ws = tmp_path / "other_workspace"
    other_ws.mkdir()
    other_dir = other_ws / "office" / "word" / "d-foreign"
    other_dir.mkdir(parents=True)
    (other_dir / "foreign.docx").write_bytes(b"x")
    conn.execute(
        """
        INSERT INTO office_documents
            (id, workspace_path, doc_type, original_filename,
             generated_filename, status, created_at, updated_at,
             metadata, derived_from, archived_at, active_spec_id)
        VALUES (?, ?, 'word', 'foreign.docx', 'foreign.docx',
                'parsed', 1000, 1000, '{"file_size_bytes": 1}',
                NULL, NULL, NULL)
        """,
        ("d-foreign", str(other_ws)),
    )
    conn.commit()

    with pytest.raises(OfficeSourceNotFoundError) as exc_info:
        resolve_office_source_path(conn, "d-foreign")
    assert exc_info.value.reason == "outside_default_workspace"


def test_resolve_source_input_exactly_one(conn, workspace):
    _insert(conn, workspace, "d-ok", doc_type="word")

    with pytest.raises(ValueError, match="必须提供"):
        resolve_source_input(conn, None, None)
    with pytest.raises(ValueError, match="不能同时提供"):
        resolve_source_input(conn, "/tmp/whatever.docx", "d-ok")


def test_resolve_source_input_doc_id_wins(conn, workspace):
    _insert(conn, workspace, "d-ok", doc_type="word", generated="g.docx")

    resolved = resolve_source_input(conn, None, "d-ok")
    assert resolved.name == "g.docx"


def test_resolve_source_input_file_path_expands_user(conn):
    resolved = resolve_source_input(conn, "~/nonexistent.docx", None)
    assert "~" not in str(resolved)
