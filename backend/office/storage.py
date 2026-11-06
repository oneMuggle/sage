"""Office document storage layer.

Two responsibilities:

1. **Path validation** — `validate_workspace()` and `generate_document_dir()`
   enforce the workspace sandbox per plan §3.3. Generated files only land in
   `<workspace>/office/<doc_type>/<doc_id>/`. Any attempt to escape the
   workspace (via `..`, absolute paths, or symlinks) raises OfficePathError.

2. **SQLite persistence** — `save_document()`, `list_documents()`, `delete_document()`,
   `archive_document()`, `restore_document()` wrap the office_documents
   table defined in backend/data/database.py. The schema is created by
   Database.init_db(); callers must initialize the DB before using these helpers.

3. **Pre-edit snapshots** — `snapshot_pre_edit()` copies the current on-disk
   file to ``<managed_dir>/.snapshots/<ts>-<filename>`` so a recent edit
   can be reverted independently of the archive/restore soft-delete path.
   Snapshot failures are non-fatal — the user's primary intent (the edit)
   always runs.

This module is **connection-agnostic** — functions take a sqlite3.Connection
so tests can use `:memory:` and production uses the real Database.get_connection().
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import time
from pathlib import Path
from typing import List, Optional, Tuple

from .errors import OfficeFileNotFoundError, OfficePathError
from .models import OfficeDocType, OfficeDocumentSummary, OfficeSnapshotInfo
from .path_safety import managed_document_directory, resolve_within, validate_doc_id
from .revision import compute_file_revision

logger = logging.getLogger(__name__)

#: 快照保留策略（技术债 L3 还账，2026-09-09 方案 Item 1.7）：
#: 每文档最多保留 SNAPSHOT_KEEP_COUNT 份、目录总量不超过
#: SNAPSHOT_MAX_TOTAL_BYTES，超限删最旧。snapshot_pre_edit 每次成功后执行。
SNAPSHOT_KEEP_COUNT = 10
SNAPSHOT_MAX_TOTAL_BYTES = 100 * 1024 * 1024  # 100 MiB


def validate_workspace(path: Path) -> Path:
    """Validate a workspace directory.

    Raises:
        OfficePathError: path doesn't exist, isn't a directory, or contains '..'
                        segments.

    Returns:
        Resolved absolute Path (symlinks resolved).
    """
    path = Path(path)

    # Reject strings that obviously try to traverse (cheap pre-check before resolve)
    if any(part == ".." for part in path.parts):
        raise OfficePathError(f"Path contains '..' traversal segment: {path}", file_path=path)

    # Resolve to absolute (handles relative paths and existing symlinks)
    resolved = path.resolve()

    if not resolved.exists():
        raise OfficePathError(f"Workspace path does not exist: {path}", file_path=path)
    if not resolved.is_dir():
        raise OfficePathError(f"Workspace path is not a directory: {path}", file_path=path)

    return resolved


def generate_document_dir(
    workspace: Path,
    doc_type: OfficeDocType,
    doc_id: str,
) -> Path:
    """Create (and return) the per-document directory.

    Layout: ``<workspace>/office/<doc_type>/<doc_id>/``

    Containment is enforced by :func:`path_safety.resolve_within`, which
    resolves the candidate path (collapsing ``..`` and following
    symlinks) and uses ``PurePath.relative_to`` for the boundary check
    instead of brittle string-prefix comparison. This closes the
    sibling-prefix attack class (``/tmp/work-evil`` vs ``/tmp/work``)
    that the previous ``str.startswith`` guard missed.

    Raises:
        OfficePathError: doc_id is unsafe, the workspace does not exist,
                        or the resolved path escapes the workspace.
    """
    workspace = validate_workspace(workspace)

    # Reuse the path_safety doc-id regex (single source of truth) and
    # the managed-directory layout helper. Centralizing prevents the
    # regex / layout from drifting if a future change adds an extra
    # segment to the on-disk layout.
    validate_doc_id(doc_id)
    candidate = managed_document_directory(workspace, doc_type, doc_id)

    # Cross-platform containment: resolve collapses ``..`` and follows
    # symlinks; ``relative_to`` then rejects any candidate that lands
    # outside the workspace. Works identically on POSIX and Windows.
    target = resolve_within(workspace, candidate)

    target.mkdir(parents=True, exist_ok=True)
    return target


def _summary_to_row(summary: OfficeDocumentSummary) -> tuple:
    """Convert OfficeDocumentSummary to a DB row tuple."""
    metadata_json = json.dumps(summary.metadata.model_dump(mode="json"))
    return (
        summary.id,
        summary.workspace_path,
        summary.doc_type.value,
        summary.original_filename,
        summary.generated_filename,
        summary.status.value,
        summary.created_at,
        summary.updated_at,
        metadata_json,
        summary.derived_from,
        summary.archived_at,
        summary.active_spec_id,
    )


def save_document(
    conn: sqlite3.Connection,
    summary: OfficeDocumentSummary,
    content_file_path: Optional[Path] = None,
) -> OfficeDocumentSummary:
    """INSERT OR REPLACE an office_documents row. Returns the saved summary.

    Also refreshes the document's content digest (the import duplicate
    detector reads it). ``content_file_path`` lets the caller pass the
    exact file it just wrote — the managed layout path is derived from the
    summary when it is omitted.
    """
    row = _summary_to_row(summary)
    conn.execute(
        """
        INSERT OR REPLACE INTO office_documents (
            id, workspace_path, doc_type, original_filename,
            generated_filename, status, created_at, updated_at, metadata,
            derived_from, archived_at, active_spec_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        row,
    )
    conn.commit()
    record_content_hash(conn, summary, file_path=content_file_path)
    return summary


def _row_to_summary(row: sqlite3.Row) -> OfficeDocumentSummary:
    """Convert a DB row to OfficeDocumentSummary."""
    from .models import (  # local import to avoid circular at module load
        OfficeDocStatus,
        OfficeDocumentMetadata,
    )

    metadata_dict = json.loads(row["metadata"]) if row["metadata"] else {}
    # ``derived_from`` / ``archived_at`` / ``active_spec_id`` are nullable
    # columns added by migrations (M0 Task 3, M2.5). ``row.keys()`` lets
    # us safely read rows from a pre-migration test fixture (or a legacy
    # DB during the brief window before init_db runs again).
    row_keys = set(row.keys())
    return OfficeDocumentSummary(
        id=row["id"],
        workspace_path=row["workspace_path"],
        doc_type=OfficeDocType(row["doc_type"]),
        original_filename=row["original_filename"],
        generated_filename=row["generated_filename"],
        status=OfficeDocStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        metadata=OfficeDocumentMetadata(**metadata_dict),
        derived_from=row["derived_from"] if "derived_from" in row_keys else None,
        archived_at=row["archived_at"] if "archived_at" in row_keys else None,
        active_spec_id=row["active_spec_id"] if "active_spec_id" in row_keys else None,
    )


#: Sort fields accepted by :func:`list_documents` (``sort=``). The value is a
#: key function over :class:`OfficeDocumentSummary` — sorting happens in Python
#: after the SQL fetch so no user input ever reaches the ORDER BY clause and
#: ``json_extract`` (absent on some bundled SQLite builds) is not required.
_SORT_KEYS = {
    "created_at": lambda doc: doc.created_at,
    "updated_at": lambda doc: doc.updated_at,
    "name": lambda doc: (doc.original_filename or doc.generated_filename).lower(),
    "size": lambda doc: doc.metadata.file_size_bytes,
}


def _escape_like(value: str) -> str:
    """Escape ``%`` / ``_`` / ``\\`` so user search text is a literal substring."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_documents(
    conn: sqlite3.Connection,
    workspace_path: str,
    include_archived: bool = False,
    q: Optional[str] = None,
    doc_type: Optional[str] = None,
    sort: Optional[str] = None,
) -> List[OfficeDocumentSummary]:
    """SELECT documents for the given workspace, optionally filtered/sorted.

    Args:
        conn: SQLite connection.
        workspace_path: Absolute workspace directory.
        include_archived: When ``False`` (default) rows with ``archived_at``
            non-NULL are filtered out so the M0 management view only shows
            "live" documents. Set ``True`` for archive-restore UIs.
        q: Filename substring search. Matches ``original_filename`` OR
            ``generated_filename`` (SQLite ``LIKE``, case-insensitive for
            ASCII). Blank/whitespace-only values are ignored.
        doc_type: Restrict to one :class:`OfficeDocType` value
            (``word`` / ``excel`` / ``ppt`` / ``pdf``). Unknown values
            yield an empty list rather than an error.
        sort: One of ``created_at`` / ``updated_at`` / ``name`` / ``size``,
            optionally prefixed with ``-`` for descending order. Unknown
            values fall back to the default ``created_at DESC``.
    """
    where = ["workspace_path = ?"]
    params: List[object] = [workspace_path]
    if not include_archived:
        where.append("archived_at IS NULL")
    if q is not None and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        where.append(
            "(COALESCE(original_filename, '') LIKE ? ESCAPE '\\'"
            " OR generated_filename LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern])
    if doc_type is not None and str(doc_type).strip():
        where.append("doc_type = ?")
        params.append(str(doc_type).strip().lower())
    sql = f"""
        SELECT id, workspace_path, doc_type, original_filename,
               generated_filename, status, created_at, updated_at, metadata,
               derived_from, archived_at, active_spec_id
        FROM office_documents
        WHERE {" AND ".join(where)}
        ORDER BY created_at DESC
    """
    cursor = conn.execute(sql, tuple(params))
    documents = [_row_to_summary(row) for row in cursor.fetchall()]

    if sort is not None:
        descending = sort.startswith("-")
        key = _SORT_KEYS.get(sort.lstrip("-"))
        if key is not None:
            # Stable sort: equal keys keep the SQL default order.
            documents.sort(key=key, reverse=descending)
    return documents


def get_document(
    conn: sqlite3.Connection,
    document_id: str,
) -> OfficeDocumentSummary | None:
    """Fetch a single office document by id.

    Returns ``None`` when the id is unknown so callers can branch on
    not-found vs. raised-error without try/except noise. Used by M0
    management endpoints to look up the canonical workspace path of a
    document before archive/delete operations.
    """
    cursor = conn.execute(
        """
        SELECT id, workspace_path, doc_type, original_filename,
               generated_filename, status, created_at, updated_at, metadata,
               derived_from, archived_at, active_spec_id
        FROM office_documents
        WHERE id = ?
        """,
        (document_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return _row_to_summary(row)


def document_path(summary: OfficeDocumentSummary) -> Path:
    """Compute the on-disk path for a document summary.

    Mirrors the layout used by :func:`generate_document_dir` and the
    Electron import gateway:

        ``<workspace>/office/<doc_type>/<id>/<filename>``

    No filesystem access; pure path arithmetic. Lets the routes layer
    show ``open``/``reveal-in-folder`` actions without re-deriving the
    layout in each caller.

    Delegates to :func:`path_safety.managed_document_directory` so the
    ``office/<docType>/<docId>`` segment is defined in exactly one
    place; adding a new ``office/<extra>`` segment in the future
    automatically flows through both functions.
    """
    return (
        managed_document_directory(Path(summary.workspace_path), summary.doc_type, summary.id)
        / summary.generated_filename
    )


def delete_document(conn: sqlite3.Connection, doc_id: str) -> bool:
    """DELETE a document by id. Returns True if a row was removed."""
    cursor = conn.execute("DELETE FROM office_documents WHERE id = ?", (doc_id,))
    conn.commit()
    delete_content_hash(conn, doc_id)
    return cursor.rowcount > 0


# ──────────────────────────────────────────────────────────────────────
# Content hash + lineage (import duplicate detection)
# ──────────────────────────────────────────────────────────────────────
#
# The digest of each managed document lives in a side table rather than in
# a column on ``office_documents``: save_document() writes with
# ``INSERT OR REPLACE``, so a column on that table would be wiped by every
# re-save. A side table keyed by the document id keeps the digest
# independent of how the main row happens to be written.


def ensure_content_hash_table(conn: sqlite3.Connection) -> None:
    """Create the content-hash side table + lookup index (idempotent)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS office_document_hashes (
            id TEXT PRIMARY KEY,
            workspace_path TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_office_doc_hashes_ws_hash
        ON office_document_hashes (workspace_path, content_hash)
        """
    )
    conn.commit()


def record_content_hash(
    conn: sqlite3.Connection,
    summary: OfficeDocumentSummary,
    file_path: Optional[Path] = None,
) -> Optional[str]:
    """Hash the document's bytes and remember them for duplicate detection.

    Best-effort by design: a document whose file is not on disk yet (a row
    saved before the writer flushed) simply has no digest and therefore
    does not take part in duplicate detection. Documents imported before
    this feature existed behave the same way — they are never reported as
    duplicates.

    Returns the stored digest, or None when it could not be computed.
    """
    target: Optional[Path]
    if file_path is not None:
        target = Path(file_path)
    else:
        try:
            target = document_path(summary)
        except (OfficePathError, OSError) as exc:
            logger.debug("content hash skipped for %s: %s", summary.id, exc)
            return None
    try:
        content_hash = compute_file_revision(target)
    except (OfficeFileNotFoundError, OSError) as exc:
        logger.debug("content hash skipped for %s: %s", summary.id, exc)
        return None
    ensure_content_hash_table(conn)
    conn.execute(
        """
        INSERT OR REPLACE INTO office_document_hashes
            (id, workspace_path, content_hash, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (summary.id, summary.workspace_path, content_hash, summary.updated_at),
    )
    conn.commit()
    return content_hash


def get_content_hash(conn: sqlite3.Connection, doc_id: str) -> Optional[str]:
    """Return the stored content digest of a document, if it has one."""
    try:
        row = conn.execute(
            "SELECT content_hash FROM office_document_hashes WHERE id = ?",
            (doc_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        # The side table has not been created yet on a fresh database.
        return None
    return row[0] if row is not None else None


def delete_content_hash(conn: sqlite3.Connection, doc_id: str) -> None:
    """Forget a document's content digest (called when its row is deleted)."""
    try:
        conn.execute("DELETE FROM office_document_hashes WHERE id = ?", (doc_id,))
    except sqlite3.OperationalError:
        # No side table yet — nothing to clean up.
        return
    conn.commit()


def find_documents_by_hash(
    conn: sqlite3.Connection,
    workspace_path: str,
    content_hash: str,
) -> List[OfficeDocumentSummary]:
    """Return the live documents in a workspace whose bytes match a digest.

    Archived rows are excluded — an archived document is not something the
    user should be warned about when importing the same file again.
    """
    ensure_content_hash_table(conn)
    try:
        rows = conn.execute(
            """
            SELECT d.id, d.workspace_path, d.doc_type, d.original_filename,
                   d.generated_filename, d.status, d.created_at, d.updated_at,
                   d.metadata, d.derived_from, d.archived_at, d.active_spec_id
            FROM office_documents d
            JOIN office_document_hashes h ON h.id = d.id
            WHERE h.content_hash = ? AND d.workspace_path = ?
              AND d.archived_at IS NULL
            ORDER BY d.created_at ASC
            """,
            (content_hash, workspace_path),
        ).fetchall()
    except sqlite3.OperationalError:
        # A legacy database without the archive column — nothing to match.
        return []
    return [_row_to_summary(row) for row in rows]


def list_duplicate_groups(
    conn: sqlite3.Connection,
    workspace_path: str,
) -> List[Tuple[str, List[OfficeDocumentSummary]]]:
    """Group live documents in a workspace by identical content digest.

    Returns ``(content_hash, documents)`` pairs, only for digests shared by
    two or more live documents. Documents without a stored digest (imported
    before hashing existed, or whose file vanished) never appear.

    Members are ordered newest-first so the UI can offer "keep newest,
    archive the rest"; groups themselves are ordered by their newest member.
    """
    ensure_content_hash_table(conn)
    try:
        rows = conn.execute(
            """
            SELECT d.id, d.workspace_path, d.doc_type, d.original_filename,
                   d.generated_filename, d.status, d.created_at, d.updated_at,
                   d.metadata, d.derived_from, d.archived_at, d.active_spec_id,
                   h.content_hash
            FROM office_documents d
            JOIN office_document_hashes h ON h.id = d.id
            WHERE d.workspace_path = ? AND d.archived_at IS NULL
            ORDER BY h.content_hash, d.created_at DESC
            """,
            (workspace_path,),
        ).fetchall()
    except sqlite3.OperationalError:
        # A legacy database without the archive column — nothing to group.
        return []

    groups: List[Tuple[str, List[OfficeDocumentSummary]]] = []
    current_hash: Optional[str] = None
    current_docs: List[OfficeDocumentSummary] = []
    for row in rows:
        digest = row["content_hash"]
        if digest != current_hash:
            if current_hash is not None and len(current_docs) > 1:
                groups.append((current_hash, current_docs))
            current_hash = digest
            current_docs = []
        current_docs.append(_row_to_summary(row))
    if current_hash is not None and len(current_docs) > 1:
        groups.append((current_hash, current_docs))
    # Newest group first (members are already newest-first within a group).
    groups.sort(key=lambda group: group[1][0].created_at, reverse=True)
    return groups


def set_document_lineage(
    conn: sqlite3.Connection,
    doc_id: str,
    derived_from: Optional[str],
) -> bool:
    """Point a document at the document it was derived from.

    Returns True iff a row matched the id.
    """
    cursor = conn.execute(
        "UPDATE office_documents SET derived_from = ? WHERE id = ?",
        (derived_from, doc_id),
    )
    conn.commit()
    return cursor.rowcount > 0


# ──────────────────────────────────────────────────────────────────────
# Archive / restore (PR-2: soft-delete lifecycle)
# ──────────────────────────────────────────────────────────────────────


def archive_document(
    conn: sqlite3.Connection,
    doc_id: str,
    now_ms: Optional[int] = None,
) -> bool:
    """Set ``archived_at`` to the current (or supplied) ms epoch.

    Soft-delete the document: the row stays, but ``list_documents(include_archived=False)``
    hides it from the default view. ``now_ms`` is injectable so unit tests
    can pin the timestamp without sleeping.

    Returns:
        True iff a row matched the id (and was actually marked archived).
    """
    timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    cursor = conn.execute(
        "UPDATE office_documents SET archived_at = ? WHERE id = ?",
        (timestamp, doc_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def restore_document(
    conn: sqlite3.Connection,
    doc_id: str,
) -> bool:
    """Clear ``archived_at`` back to NULL (un-archive / live again).

    Returns:
        True iff a row matched the id. The caller treats unknown ids as
        not-found identically to unknown ids passed to ``archive_document``
        so the two operations stay symmetric.
    """
    cursor = conn.execute(
        "UPDATE office_documents SET archived_at = NULL WHERE id = ?",
        (doc_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


# ──────────────────────────────────────────────────────────────────────
# Pre-edit snapshots (PR-2: "undo last edit" path)
# ──────────────────────────────────────────────────────────────────────


def snapshot_pre_edit(
    summary: OfficeDocumentSummary,
    *,
    now_ms: Optional[int] = None,
) -> Optional[Path]:
    """Copy the current on-disk file to a timestamped sibling snapshot.

    Called by :class:`backend.office.tool_service.OfficeToolService.update`
    immediately before applying the edit ops. The new content overwrites
    the original file; this snapshot keeps the *pre-edit* bytes recoverable
    so a user can revert a single edit without going through the
    archive/restore soft-delete path.

    Layout:
        ``<managed_dir>/.snapshots/<int(now_ms)>-<generated_filename>``

    The ``.snapshots`` subdirectory is created on demand (``mkdir -p``).
    The timestamp is millisecond epoch so two edits in the same second
    still produce distinct filenames.

    Returns:
        The destination ``Path`` on success; ``None`` on any failure
        (source missing, permission denied, IO error). Snapshots are
        best-effort: a failed snapshot must NEVER block the user's edit.
    """
    try:
        source = document_path(summary)
        if not source.is_file():
            return None
        managed_dir = source.parent
        snapshot_dir = managed_dir / ".snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        ts = int(now_ms if now_ms is not None else time.time() * 1000)
        destination = snapshot_dir / f"{ts}-{summary.generated_filename}"
        # ``copy2`` preserves mtime/atime so the snapshot is byte-identical
        # to what the editor was about to overwrite.
        shutil.copy2(source, destination)
        _enforce_snapshot_retention(snapshot_dir)
        return destination
    except (OSError, ValueError):
        logger.warning(
            "snapshot_pre_edit failed for doc=%s (non-fatal; edit will proceed)",
            summary.id,
        )
        return None


def _parse_snapshot_ts(name: str) -> Optional[int]:
    """Return the millisecond epoch encoded in ``<ms>-<filename>``, else None."""
    head, sep, _rest = name.partition("-")
    if not sep or not head.isdigit():
        return None
    return int(head)


def _snapshot_dir_for(summary: OfficeDocumentSummary) -> Optional[Path]:
    """Return the document's ``.snapshots`` dir, or None when unavailable."""
    source = document_path(summary)
    if not source.is_file():
        return None
    return source.parent / ".snapshots"


def _enforce_snapshot_retention(snapshot_dir: Path) -> None:
    """Prune oldest snapshots beyond count/size limits (best-effort).

    Failures are logged and swallowed — retention must never break the
    edit that just succeeded (same contract as snapshot_pre_edit itself).
    """
    try:
        entries: List[Tuple[int, Path, int]] = []
        for entry in snapshot_dir.iterdir():
            if not entry.is_file():
                continue
            ts = _parse_snapshot_ts(entry.name)
            if ts is None:
                continue  # 非快照命名规则的文件不动
            entries.append((ts, entry, entry.stat().st_size))
        if len(entries) <= SNAPSHOT_KEEP_COUNT and sum(
            e[2] for e in entries
        ) <= SNAPSHOT_MAX_TOTAL_BYTES:
            return
        # 最旧的在前，逐个删除直到数量与容量两项限制都满足
        entries.sort(key=lambda e: e[0])
        total = sum(e[2] for e in entries)
        excess = max(0, len(entries) - SNAPSHOT_KEEP_COUNT)
        for _ts, path, size in entries:
            if excess <= 0 and total <= SNAPSHOT_MAX_TOTAL_BYTES:
                break
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(
                    "snapshot prune unlink failed (%s): %s", path.name, exc
                )
                continue  # 删不掉的不再重试，避免死循环
            excess -= 1
            total -= size
    except OSError as exc:
        logger.warning("snapshot retention prune failed (non-fatal): %s", exc)


def list_snapshots(summary: OfficeDocumentSummary) -> List[OfficeSnapshotInfo]:
    """List a document's pre-edit snapshots, newest first.

    只认 ``<ms>-<generated_filename>`` 命名规则的文件；目录缺失或文档
    文件不在盘上时返回空列表（无快照不是错误）。
    """
    try:
        snapshot_dir = _snapshot_dir_for(summary)
        if snapshot_dir is None or not snapshot_dir.is_dir():
            return []
        infos: List[OfficeSnapshotInfo] = []
        for entry in snapshot_dir.iterdir():
            if not entry.is_file():
                continue
            ts = _parse_snapshot_ts(entry.name)
            if ts is None or not entry.name.endswith(summary.generated_filename):
                continue
            infos.append(
                OfficeSnapshotInfo(
                    snapshot_id=entry.name,
                    size_bytes=entry.stat().st_size,
                    created_at=ts,
                )
            )
        infos.sort(key=lambda info: info.created_at, reverse=True)
        return infos
    except OSError as exc:
        logger.warning("list_snapshots failed for doc=%s: %s", summary.id, exc)
        return []


def restore_from_snapshot(
    conn: sqlite3.Connection,
    summary: OfficeDocumentSummary,
    snapshot_id: str,
    *,
    now_ms: Optional[int] = None,
) -> OfficeDocumentSummary:
    """Restore the document file from a snapshot; return the refreshed summary.

    恢复前先把当前文件再快照一份（恢复操作本身也可撤销），随后用
    ``copy2`` 覆盖主文件并刷新 DB 的 ``updated_at`` / ``metadata``。

    Raises:
        OfficeFileNotFoundError: snapshot_id 不存在或不匹配命名规则。
        OfficePathError: snapshot_id 尝试路径穿越（``/``、``..`` 等）。
    """
    from .errors import OfficeFileNotFoundError  # local: avoids import cycle

    if any(sep in snapshot_id for sep in ("/", "\\", "..")):
        raise OfficePathError(
            f"Invalid snapshot id: {snapshot_id}", file_path=Path(snapshot_id)
        )
    snapshot_dir = _snapshot_dir_for(summary)
    target = snapshot_dir / snapshot_id if snapshot_dir is not None else None
    if target is None or not target.is_file():
        # OfficeFileNotFoundError 只接受 file_path（message 由基类拼装）
        raise OfficeFileNotFoundError(Path(snapshot_id))

    # 恢复前留存"恢复前"状态（best-effort，失败不阻断恢复）
    snapshot_pre_edit(summary, now_ms=now_ms)
    destination = document_path(summary)
    shutil.copy2(target, destination)

    ts = int(now_ms if now_ms is not None else time.time() * 1000)
    summary.metadata.file_size_bytes = destination.stat().st_size
    summary.updated_at = ts
    save_document(conn, summary)
    return summary
