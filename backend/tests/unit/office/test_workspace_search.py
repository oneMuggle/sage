"""Unit tests for bounded session workspace file search."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import List

import pytest

from backend.data.database import Database
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.session_workspace import bind_session_workspace
from backend.office.storage import save_document
from backend.office.workspace_search import (
    _MAX_SCAN_CANDIDATES,
    WorkspaceSearchResult,
    search_workspace_files,
)


@pytest.fixture()
def conn() -> sqlite3.Connection:
    db = Database(":memory:")
    db.init_db()
    connection = db.get_connection()
    connection.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("session-a", "Search", 1, 1),
    )
    connection.commit()
    return connection


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "workspace"
    path.mkdir()
    return path


@pytest.fixture()
def binding(conn: sqlite3.Connection, workspace: Path):
    return bind_session_workspace(conn, "session-a", str(workspace), now_ms=1)


def _save_managed_document(
    conn: sqlite3.Connection,
    workspace: Path,
    *,
    doc_id: str,
    filename: str,
    doc_type: OfficeDocType = OfficeDocType.PPT,
    size_bytes: int = 12,
) -> OfficeDocumentSummary:
    managed_dir = workspace / "office" / doc_type.value / doc_id
    managed_dir.mkdir(parents=True)
    (managed_dir / filename).write_bytes(b"x" * size_bytes)
    return save_document(
        conn,
        OfficeDocumentSummary(
            id=doc_id,
            workspace_path=str(workspace.resolve()),
            doc_type=doc_type,
            original_filename=None,
            generated_filename=filename,
            status=OfficeDocStatus.GENERATED,
            created_at=1,
            updated_at=1,
            metadata=OfficeDocumentMetadata(file_size_bytes=size_bytes),
        ),
    )


def test_search_empty_query_returns_no_results(conn: sqlite3.Connection, binding) -> None:
    assert search_workspace_files(conn, binding.session_id, "", limit=20) == []


def test_search_matches_case_insensitively(
    conn: sqlite3.Connection, binding, workspace: Path
) -> None:
    (workspace / "Quarterly-REPORT.txt").write_text("data", encoding="utf-8")
    assert [r.name for r in search_workspace_files(conn, binding.session_id, "report", 20)] == [
        "Quarterly-REPORT.txt"
    ]


def test_search_returns_managed_office_result_before_files(
    conn: sqlite3.Connection, binding, workspace: Path
) -> None:
    _save_managed_document(conn, workspace, doc_id="doc-1", filename="report.pptx", size_bytes=7)
    (workspace / "report-notes.txt").write_text("notes", encoding="utf-8")
    results = search_workspace_files(conn, binding.session_id, "report", 20)
    assert results[0] == WorkspaceSearchResult(
        name="report.pptx",
        kind="office-ppt",
        doc_type=OfficeDocType.PPT,
        doc_id="doc-1",
        size_bytes=7,
        needs_import=False,
        source_path=None,
    )
    assert results[1].kind == "file"


def test_search_marks_unmanaged_office_file_for_import(
    conn: sqlite3.Connection, binding, workspace: Path
) -> None:
    source = workspace / "incoming" / "budget.XLSX"
    source.parent.mkdir()
    source.write_bytes(b"sheet")
    assert search_workspace_files(conn, binding.session_id, "budget", 20) == [
        WorkspaceSearchResult(
            name="incoming/budget.XLSX",
            kind="office-excel",
            doc_type=OfficeDocType.EXCEL,
            doc_id=None,
            size_bytes=5,
            needs_import=True,
            source_path=str(source.resolve()),
        )
    ]


def test_search_returns_normal_file_without_source_path(
    conn: sqlite3.Connection, binding, workspace: Path
) -> None:
    target = workspace / "notes" / "report.md"
    target.parent.mkdir()
    target.write_text("hello", encoding="utf-8")
    assert search_workspace_files(conn, binding.session_id, "report", 20) == [
        WorkspaceSearchResult(
            name="notes/report.md",
            kind="file",
            doc_type=None,
            doc_id=None,
            size_bytes=5,
            needs_import=False,
            source_path=None,
        )
    ]


def test_search_deduplicates_managed_office_file(
    conn: sqlite3.Connection, binding, workspace: Path
) -> None:
    managed_doc = _save_managed_document(conn, workspace, doc_id="doc-1", filename="report.pptx")
    results = search_workspace_files(conn, binding.session_id, "report", 20)
    assert len(results) == 1
    assert results[0].doc_id == managed_doc.id
    assert results[0].needs_import is False
    assert results[0].source_path is None


def test_search_does_not_reclassify_managed_file_when_only_directory_matches(
    conn: sqlite3.Connection, binding, workspace: Path
) -> None:
    _save_managed_document(conn, workspace, doc_id="matching-directory", filename="unrelated.pptx")

    results = search_workspace_files(conn, binding.session_id, "matching-directory", limit=20)

    assert results == []


def test_search_skips_symlink_escape(
    conn: sqlite3.Connection, binding, workspace: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside-report.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        (workspace / "linked-report.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not supported")
    assert search_workspace_files(conn, binding.session_id, "report", 20) == []


def test_search_rejects_query_longer_than_200_code_points(
    conn: sqlite3.Connection, binding
) -> None:
    with pytest.raises(ValueError, match="200"):
        search_workspace_files(conn, binding.session_id, "界" * 201, 20)


@pytest.mark.parametrize("limit", [0, 51])
def test_search_rejects_out_of_range_limit(conn: sqlite3.Connection, binding, limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        search_workspace_files(conn, binding.session_id, "report", limit)


def test_search_applies_one_combined_cap_to_managed_and_regular_results(
    conn: sqlite3.Connection, binding, workspace: Path
) -> None:
    _save_managed_document(conn, workspace, doc_id="a", filename="report-a.pptx")
    _save_managed_document(
        conn, workspace, doc_id="b", filename="report-b.docx", doc_type=OfficeDocType.WORD
    )
    for index in range(3):
        (workspace / f"report-{index}.txt").write_text("x", encoding="utf-8")
    results: List[WorkspaceSearchResult] = search_workspace_files(
        conn, binding.session_id, "report", 3
    )
    assert len(results) == 3
    assert [result.doc_id for result in results[:2]] == ["a", "b"]
    assert results[2].kind == "file"


def test_search_rejects_workspace_root_replaced_by_symlink(
    conn: sqlite3.Connection, binding, workspace: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "report.txt").write_text("secret", encoding="utf-8")
    original = tmp_path / "moved-workspace"
    workspace.rename(original)
    try:
        workspace.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not supported")

    from backend.office.workspace_errors import WorkspaceRevokedError

    with pytest.raises(WorkspaceRevokedError):
        search_workspace_files(conn, binding.session_id, "report", limit=20)


def test_search_caps_candidate_walk_at_5000(
    conn: sqlite3.Connection, binding, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yielded_walk_entries = 0

    def many_candidates(top: Path, topdown: bool = True, onerror=None, followlinks: bool = False):
        nonlocal yielded_walk_entries
        assert Path(top) == workspace
        assert topdown is True
        assert followlinks is False
        for index in range(_MAX_SCAN_CANDIDATES + 1_000):
            yielded_walk_entries += 1
            yield str(workspace), [], [f"report-{index}.txt"]

    monkeypatch.setattr(os, "walk", many_candidates)

    results = search_workspace_files(conn, binding.session_id, "no-match", limit=50)

    assert len(results) <= 50
    assert yielded_walk_entries == _MAX_SCAN_CANDIDATES
