"""Snapshot management tests (2026-09-09 方案 Item 1.7).

Covers the new snapshot lifecycle beyond PR-2's bare ``snapshot_pre_edit``:
- ``list_snapshots``: newest-first parsing of ``<ms>-<filename>`` entries,
  ignores foreign files, empty (or missing) dir -> empty list.
- Retention policy wired into ``snapshot_pre_edit``: keeps the newest
  ``SNAPSHOT_KEEP_COUNT`` snapshots; drops older ones; honours the byte cap.
- ``restore_from_snapshot``: reverts file bytes, leaves a safety snapshot of
  the pre-restore state, refreshes DB ``updated_at`` / ``file_size_bytes``;
  unknown / traversal ids raise.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.office import storage
from backend.office.errors import OfficeFileNotFoundError, OfficePathError
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.storage import (
    document_path,
    list_snapshots,
    restore_from_snapshot,
    snapshot_pre_edit,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    """In-memory SQLite connection with the office_documents table created."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
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
            archived_at INTEGER
        )
        """
    )
    conn.commit()
    return conn


def _seed_doc_with_file(tmp_path: Path, *, content: bytes = b"v0") -> OfficeDocumentSummary:
    workspace = tmp_path / "ws"
    managed_dir = workspace / "office" / "word" / "doc-1"
    managed_dir.mkdir(parents=True)
    (managed_dir / "out.docx").write_bytes(content)
    return OfficeDocumentSummary(
        id="doc-1",
        workspace_path=str(workspace),
        doc_type=OfficeDocType.WORD,
        original_filename=None,
        generated_filename="out.docx",
        status=OfficeDocStatus.GENERATED,
        created_at=1_700_000_000_000,
        updated_at=1_700_000_000_000,
        metadata=OfficeDocumentMetadata(file_size_bytes=len(content)),
    )


# ──────────────────────────────────────────────────────────────────────
# list_snapshots
# ──────────────────────────────────────────────────────────────────────


def test_list_snapshots_newest_first_and_parses_metadata(tmp_path: Path):
    summary = _seed_doc_with_file(tmp_path)
    snap_dir = document_path(summary).parent / ".snapshots"
    snap_dir.mkdir()
    (snap_dir / "1700000001000-out.docx").write_bytes(b"a" * 10)
    (snap_dir / "1700000002000-out.docx").write_bytes(b"b" * 20)

    infos = list_snapshots(summary)
    assert [i.snapshot_id for i in infos] == [
        "1700000002000-out.docx",
        "1700000001000-out.docx",
    ]
    assert infos[0].created_at == 1_700_000_002_000
    assert infos[0].size_bytes == 20
    assert infos[1].size_bytes == 10


def test_list_snapshots_ignores_foreign_files(tmp_path: Path):
    summary = _seed_doc_with_file(tmp_path)
    snap_dir = document_path(summary).parent / ".snapshots"
    snap_dir.mkdir()
    (snap_dir / "not-a-snapshot.txt").write_bytes(b"x")
    (snap_dir / "subdir").mkdir()
    assert list_snapshots(summary) == []


def test_list_snapshots_empty_when_no_dir_or_no_file(tmp_path: Path):
    summary = _seed_doc_with_file(tmp_path)
    assert list_snapshots(summary) == []
    # 文档主文件不在盘上时也不抛错
    document_path(summary).unlink()
    assert list_snapshots(summary) == []


# ──────────────────────────────────────────────────────────────────────
# retention (wired into snapshot_pre_edit)
# ──────────────────────────────────────────────────────────────────────


def test_retention_keeps_newest_count(tmp_path: Path):
    summary = _seed_doc_with_file(tmp_path)
    base = 1_700_000_000_000
    for i in range(12):
        document_path(summary).write_bytes(f"v{i}".encode())
        snapshot_pre_edit(summary, now_ms=base + i * 1000)

    snap_dir = document_path(summary).parent / ".snapshots"
    names = {p.name for p in snap_dir.iterdir() if p.is_file()}
    assert len(names) == storage.SNAPSHOT_KEEP_COUNT
    # 最旧的两份（v0、v1）被清掉，最新的保留
    assert f"{base + 11_000}-out.docx" in names
    assert f"{base}-out.docx" not in names
    assert f"{base + 1000}-out.docx" not in names


def test_retention_honours_byte_cap(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(storage, "SNAPSHOT_MAX_TOTAL_BYTES", 50)
    summary = _seed_doc_with_file(tmp_path)
    base = 1_700_000_000_000
    # 每份 40 字节 → 总量超 50 后只留 1 份
    for i in range(4):
        document_path(summary).write_bytes(b"x" * 40)
        snapshot_pre_edit(summary, now_ms=base + i * 1000)

    snap_dir = document_path(summary).parent / ".snapshots"
    names = sorted(p.name for p in snap_dir.iterdir() if p.is_file())
    assert names == [f"{base + 3000}-out.docx"]


def test_retention_swallows_prune_errors(tmp_path: Path, monkeypatch):
    """Prune 失败不能阻断快照本身（与 snapshot_pre_edit 同一 best-effort 契约）。"""
    summary = _seed_doc_with_file(tmp_path)
    monkeypatch.setattr(storage, "SNAPSHOT_KEEP_COUNT", 0)

    def _boom(self, *args, **kwargs):
        raise OSError("locked")

    monkeypatch.setattr(Path, "unlink", _boom)
    result = snapshot_pre_edit(summary, now_ms=1)
    assert result is not None
    assert result.is_file()


# ──────────────────────────────────────────────────────────────────────
# restore_from_snapshot
# ──────────────────────────────────────────────────────────────────────


def test_restore_from_snapshot_reverts_bytes_and_leaves_safety_snapshot(
    tmp_path: Path, db_conn: sqlite3.Connection
):
    summary = _seed_doc_with_file(tmp_path, content=b"v1")
    snapshot_pre_edit(summary, now_ms=1_700_000_001_000)
    # 模拟一次编辑：主文件变成 v2
    document_path(summary).write_bytes(b"v2")

    updated = restore_from_snapshot(
        db_conn, summary, "1700000001000-out.docx", now_ms=1_700_000_009_000
    )

    assert document_path(summary).read_bytes() == b"v1"
    assert updated.updated_at == 1_700_000_009_000
    assert updated.metadata.file_size_bytes == 2
    # 恢复前的 v2 也被留了快照（恢复操作本身可撤销）
    snap_dir = document_path(summary).parent / ".snapshots"
    safety = snap_dir / "1700000009000-out.docx"
    assert safety.is_file()
    assert safety.read_bytes() == b"v2"
    # DB 行同步刷新
    row = db_conn.execute(
        "SELECT updated_at, metadata FROM office_documents WHERE id = 'doc-1'"
    ).fetchone()
    assert row["updated_at"] == 1_700_000_009_000
    assert '"file_size_bytes": 2' in row["metadata"]


def test_restore_from_snapshot_unknown_id_raises(
    tmp_path: Path, db_conn: sqlite3.Connection
):
    summary = _seed_doc_with_file(tmp_path)
    with pytest.raises(OfficeFileNotFoundError):
        restore_from_snapshot(db_conn, summary, "1700000001000-out.docx")


def test_restore_from_snapshot_rejects_traversal(
    tmp_path: Path, db_conn: sqlite3.Connection
):
    summary = _seed_doc_with_file(tmp_path)
    for bad in ("../evil.docx", "a/b.docx", "a\\b.docx"):
        with pytest.raises(OfficePathError):
            restore_from_snapshot(db_conn, summary, bad)


def test_restore_from_snapshot_persists_row_when_absent(
    tmp_path: Path, db_conn: sqlite3.Connection
):
    """DB 无行时 restore 也能落一行（save_document upsert 语义）。"""
    summary = _seed_doc_with_file(tmp_path, content=b"v1")
    snapshot_pre_edit(summary, now_ms=1_000)
    document_path(summary).write_bytes(b"v2")

    restore_from_snapshot(db_conn, summary, "1000-out.docx", now_ms=2_000)

    row = db_conn.execute(
        "SELECT id, updated_at FROM office_documents WHERE id = 'doc-1'"
    ).fetchone()
    assert row is not None
    assert row["updated_at"] == 2_000
