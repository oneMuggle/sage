"""Quarantine-based staging cleanup: recoverable moves, never blind deletion.

Audit item #10 follow-up, quarantine mode approved 2026-09-17.

Contract
--------
1. ``plan_quarantine`` is read-only. It widens the evidence base beyond
   :mod:`backend.office.staging_references`: exact id/lineage columns,
   registered workspace paths, journal output paths, a token scan of every
   office TEXT/BLOB cell, and a bounded on-disk scan that also looks inside zip
   containers (.docx/.pptx/.xlsx), whose relationship parts can embed another
   document's id or path. Candidates are classified ``referenced`` /
   ``no_reference_found`` / ``unknown`` / ``fresh``.
   A staged import that Electron has not marked completed is treated as an
   active lease and retained regardless of database evidence, matching
   ``previewOfficeStaging``: a dead owner pid is a review candidate, never
   clearance.
2. ``quarantine_run`` acts only on ``no_reference_found`` candidates and only
   when ``dry_run=False``. Bytes are copied into
   ``<workspace>/office/.quarantine`` with per-file SHA-256 verification and an
   append-only fsynced manifest; the source is removed only after the copy is
   proven identical. An interrupted run is resumed (completed or rolled back)
   before any new work.
3. ``restore_entry`` copies bytes back to the original path and re-verifies.
4. ``purge_entry`` is the only destructive verb: refused unless the operator
   passes ``--allow-permanent-deletion`` **and** retypes the entry id, and it
   refuses entries inside the retention window.

Conservatism rules: referenced, registered-workspace, unknown, fresh, empty,
linked, locked, hash-ambiguous and over-budget candidates are always retained.
``no_reference_found`` is never proof of orphanhood, and no code path here
deletes user data implicitly.

Python 3.8 compatible (typing.* generics, no PEP 604) so it can be
cherry-picked to ``release/win7``.
"""

from __future__ import annotations

import argparse
import calendar
import contextlib
import ctypes
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .staging_references import inspect_references

__all__ = [
    "DOC_TYPES",
    "QUARANTINE_SUBDIR",
    "collect_candidates",
    "inspect_candidate",
    "main",
    "plan_quarantine",
    "purge_entry",
    "quarantine_report",
    "quarantine_run",
    "restore_entry",
]

DOC_TYPES: Tuple[str, ...] = ("word", "ppt", "excel", "pdf")
DOC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
#: Tokens that could be a document id (also catches ids inside paths/JSON).
_TOKEN_RE = re.compile(rb"[A-Za-z0-9_-]{4,128}")
_SEPARATORS = "/" + chr(92)

QUARANTINE_SUBDIR = Path("office") / ".quarantine"
MANIFEST_NAME = "manifest.jsonl"
LOCK_NAME = "quarantine.lock"

MANIFEST_VERSION = 1
DEFAULT_QUIET_HOURS = 24
DEFAULT_RETENTION_DAYS = 7
DEFAULT_SCAN_BUDGET_BYTES = 8 * 1024 * 1024
DEFAULT_SCAN_FILE_BYTES = 2 * 1024 * 1024
MAX_CANDIDATES = 5000
MAX_SCAN_FILES = 20000
MAX_DB_ROWS = 20000
_ZIP_SUFFIXES = frozenset({".docx", ".pptx", ".xlsx", ".odt", ".ods", ".odp", ".zip", ".jar"})

_TEXT_TABLES: Tuple[str, ...] = (
    "office_documents",
    "office_self_checks",
    "office_journal_specs",
    "office_journal_generations",
)
_REQUIRED_TABLES: Tuple[str, ...] = ("office_documents",)

#: Import sentinels written by ``electron/officeStaging.ts``. They are the
#: cross-process lease: a staged import that has not been marked completed is
#: in flight (or awaiting human review) and must never be moved.
STAGING_MARKER = ".sage-import-v1.json"
COMPLETED_MARKER = ".sage-import-completed"
#: Mirrors ``STAGING_REVIEW_AGE_MS``; reported for parity, never used to clear.
STAGING_REVIEW_AGE_MS = 7 * 24 * 60 * 60 * 1000
_MARKER_MAX_BYTES = 4096
#: A candidate's own sentinels are not third-party references; excluding them
#: from the scans keeps the lease semantics observable instead of letting a
#: directory "reference itself".
_SELF_EVIDENCE_NAMES = frozenset({STAGING_MARKER, COMPLETED_MARKER, MANIFEST_NAME})
#: A staging dir inside a workspace the app still registers is always retained.
_WORKSPACE_TABLES: Tuple[str, ...] = (
    "office_documents",
    "office_journal_generations",
    "office_journal_specs",
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _utc(ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000))


def _parse_utc(value: str) -> int:
    return int(calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))) * 1000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_dir(directory: Path) -> None:
    """Best-effort directory fsync so renames survive a power loss."""
    try:
        handle = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        with contextlib.suppress(OSError):
            os.fsync(handle)
    finally:
        os.close(handle)


def _tokens(blob: bytes) -> Set[bytes]:
    return set(_TOKEN_RE.findall(blob))


def _digest_map(entries: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    return {item["rel"]: item["sha256"] for item in entries}


class _ExclusiveDirectory:  # noqa: UP037 — py3.8-compatible forward refs
    """Hold a no-sharing handle on a directory while its bytes are copied.

    On Windows this makes a concurrent writer (in-flight import, Word lock,
    editor save) fail either our open or its own write, which is the
    coordination available without an application-level lease. Failing to
    obtain the handle means the candidate is retained, never force-copied.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.fd: Optional[int] = None
        self._win_handle: Optional[int] = None

    def __enter__(self) -> _ExclusiveDirectory:
        if sys.platform == "win32":
            # One handle only: opening with FILE_SHARE_NONE after an os.open()
            # handle would conflict with ourselves and report a false "busy".
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            invalid = ctypes.c_void_p(-1).value
            handle = kernel32.CreateFileW(
                str(self.directory),
                0,  # no access rights needed to hold the name
                0,  # FILE_SHARE_NONE
                None,
                3,  # OPEN_EXISTING
                0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS
                None,
            )
            if handle == invalid:
                raise OSError("directory_busy_exclusive_open_refused")
            self._win_handle = handle
            return self
        flags = os.O_RDONLY
        for extra in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC"):
            flags |= getattr(os, extra, 0)
        self.fd = os.open(str(self.directory), flags)
        return self

    def __exit__(self, *exc_info: Any) -> None:
        if self._win_handle is not None:
            ctypes.windll.kernel32.CloseHandle(self._win_handle)  # type: ignore[attr-defined]
            self._win_handle = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class _Lock:
    """Single-writer advisory lock guarding manifest mutations."""

    def __init__(self, root: Path) -> None:
        self.path = root / LOCK_NAME
        self.fd: Optional[int] = None

    def __enter__(self) -> _Lock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise RuntimeError("quarantine_busy") from None
        os.write(
            self.fd,
            json.dumps({"pid": os.getpid(), "acquired_at": _utc(_now_ms())}).encode(),
        )
        os.fsync(self.fd)
        return self

    def __exit__(self, *exc_info: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        with contextlib.suppress(OSError):
            self.path.unlink()


class _Manifest:
    """Append-only JSONL manifest; every record is fsynced before use."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / MANIFEST_NAME

    def append(self, record: Dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_dir(self.root)

    def records(self) -> List[Dict[str, Any]]:
        if not self.path.is_file():
            return []
        out: List[Dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                text = raw_line.strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except json.JSONDecodeError:
                    record = {"action": "corrupt_record", "raw": text[:200]}
                if isinstance(record, dict):
                    out.append(record)
        return out

    def entries(self) -> Dict[str, Dict[str, Any]]:
        """Latest state per quarantine id (done/restored/purged records only)."""
        state: Dict[str, Dict[str, Any]] = {}
        for record in self.records():
            qid = record.get("quarantine_id")
            action = record.get("action")
            if not qid or action not in ("done", "restored", "purged"):
                continue
            if qid not in state:
                state[qid] = dict(record)
                continue
            for key in (
                "action",
                "at",
                "restored_to",
                "purge_confirmed_id",
                "bytes",
                "eligible_for_purge_after",
            ):
                if key in record:
                    state[qid][key] = record[key]
        return state


def _tree_digest(directory: Path) -> Tuple[List[Dict[str, Any]], int]:
    """SHA-256 + size + mtime for every regular file, sorted by relative path."""
    entries: List[Dict[str, Any]] = []
    total = 0
    for path in sorted(directory.rglob("*"), key=lambda p: p.as_posix()):
        if path.is_dir():
            continue
        stat_result = path.lstat()
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("non_regular_file_in_candidate")
        entries.append(
            {
                "rel": path.relative_to(directory).as_posix(),
                "size": int(stat_result.st_size),
                "mtime_ms": int(stat_result.st_mtime * 1000),
                "sha256": _sha256(path),
            }
        )
        total += int(stat_result.st_size)
    return entries, total


def _copy_tree_verified(source: Path, destination: Path, entries: Sequence[Dict[str, Any]]) -> None:
    """Copy each listed file (exclusive create) and re-verify its hash."""
    destination.mkdir(parents=True, exist_ok=True)
    for item in entries:
        rel = Path(item["rel"])
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            raise RuntimeError("quarantine_target_exists")
        src = source / rel
        if src.is_symlink() or not src.is_file():
            raise RuntimeError("candidate_file_not_regular")
        shutil.copyfile(str(src), str(target))
        shutil.copystat(str(src), str(target))
        if _sha256(target) != item["sha256"]:
            raise RuntimeError("quarantine_copy_hash_mismatch")
    _fsync_dir(destination)


def _remove_tree_verified(
    source: Path, entries: Sequence[Dict[str, Any]]
) -> Tuple[bool, List[str]]:
    """Delete the source tree only where content still matches the copy.

    Returns ``(fully_removed, ambiguous)``. Hash drift or a vanished file means
    the candidate changed under us, so the source is left untouched and flagged
    for human review: we cannot tell which copy is authoritative.
    """
    ambiguous: List[str] = []
    for item in entries:
        path = source / Path(item["rel"])
        try:
            stat_result = path.lstat()
        except OSError:
            ambiguous.append(item["rel"])
            continue
        if not path.is_file() or path.is_symlink():
            ambiguous.append(item["rel"])
            continue
        if int(stat_result.st_size) != int(item["size"]) or _sha256(path) != item["sha256"]:
            ambiguous.append(item["rel"])
    if ambiguous:
        return False, ambiguous
    for item in entries:
        (source / Path(item["rel"])).unlink()
    for path in sorted(source.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                return False, ["<directory_not_empty>"]
    source.rmdir()
    return True, []


def _open_ro(database: Path) -> sqlite3.Connection:
    # mode=ro (never immutable=1) so a live WAL stays visible.
    return sqlite3.connect(str(database.resolve().as_uri()) + "?mode=ro", uri=True, timeout=1)


def _existing_tables(connection: sqlite3.Connection) -> Set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {str(row[0]) for row in rows}


def _owner_may_be_alive(pid: int) -> Optional[bool]:
    """Advisory liveness probe. ``None`` means "cannot tell", never "dead"."""
    if pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError, AttributeError):
        return None
    return True


def _import_lease(  # noqa: PLR0911 — every early return is a distinct retain verdict
    directory: Path, doc_id: str
) -> Dict[str, Any]:
    """Read the Electron import sentinels for one staging directory.

    Semantics mirror ``previewOfficeStaging`` and stay deliberately more
    conservative: an owner pid that looks dead is *not* clearance, because the
    backend commit may have succeeded without the renderer sending
    ``complete-import``, and pids get reused. Only an explicit completion
    sentinel ends the lease; anything unreadable keeps it.
    """
    lease: Dict[str, Any] = {
        "marker_present": False,
        "completed": False,
        "active": False,
        "state": "none",
        "token_matches": None,
        "created_at": None,
        "owner_pid": None,
        "owner_alive": None,
    }
    marker = directory / STAGING_MARKER
    try:
        lease["completed"] = (directory / COMPLETED_MARKER).exists()
    except OSError:
        lease["completed"] = False
    try:
        info = marker.lstat()
    except FileNotFoundError:
        lease["state"] = "completed" if lease["completed"] else "none"
        return lease
    except OSError:
        lease.update(state="invalid", marker_present=True)
        return lease
    lease["marker_present"] = True
    if not stat.S_ISREG(info.st_mode):
        lease["state"] = "invalid"
        return lease
    if info.st_size > _MARKER_MAX_BYTES:
        lease["state"] = "invalid"
        return lease
    try:
        evidence = json.loads(marker.read_bytes().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        lease["state"] = "invalid"
        return lease
    if not isinstance(evidence, dict):
        lease["state"] = "invalid"
        return lease
    token = evidence.get("token")
    created = evidence.get("createdAt")
    owner = evidence.get("ownerPid")
    lease["token_matches"] = token == doc_id if isinstance(token, str) else None
    lease["created_at"] = created if isinstance(created, int) and created >= 0 else None
    lease["owner_pid"] = owner if isinstance(owner, int) and owner > 0 else None
    if lease["owner_pid"] is not None:
        lease["owner_alive"] = _owner_may_be_alive(lease["owner_pid"])
    if evidence.get("version") != 1 or lease["token_matches"] is not True:
        lease["state"] = "invalid"
        return lease
    if lease["created_at"] is None:
        lease["state"] = "invalid"
        return lease
    if lease["completed"]:
        lease["state"] = "completed"
        return lease
    lease["active"] = True
    lease["state"] = "active" if lease["owner_alive"] is not False else "review"
    return lease


def _registered_workspaces(  # noqa: PLR0911 — each early exit is a distinct retain path
    connection: sqlite3.Connection, notes: List[str]
) -> List[Path]:
    """Absolute workspace roots the application still references."""
    tables = _existing_tables(connection)
    out: List[Path] = []
    for table in _WORKSPACE_TABLES:
        if table not in tables:
            if table in _REQUIRED_TABLES:
                notes.append("missing_required_tables:" + table)
            else:
                notes.append("missing_optional_table:" + table)
            continue
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(" + table + ")")}
        if "workspace_path" not in columns:
            notes.append("missing_workspace_column:" + table)
            continue
        try:
            rows = connection.execute(
                'SELECT DISTINCT workspace_path FROM "' + table + '"'
            ).fetchall()
        except sqlite3.Error:
            notes.append("workspace_query_failed:" + table)
            continue
        for row in rows:
            value = row[0]
            if not isinstance(value, str) or not value:
                continue
            candidate = Path(value)
            if not candidate.is_absolute():
                notes.append("relative_workspace_path:" + table)
                continue
            try:
                out.append(candidate.resolve())
            except OSError:
                notes.append("unresolvable_workspace_path:" + table)
    return out


def _workspace_labels(directory: Path, registered: Iterable[Path]) -> List[str]:
    """Labels for every registered workspace that contains this directory."""
    labels: List[str] = []
    try:
        resolved_text = str(directory.resolve())
    except OSError:
        return labels
    for root in registered:
        root_text = str(root)
        if resolved_text == root_text:
            continue  # the workspace root itself is not a staging directory
        prefix = root_text.rstrip(_SEPARATORS) + os.sep
        if resolved_text.startswith(prefix) or resolved_text.casefold().startswith(
            prefix.casefold()
        ):
            labels.append("registered_workspace:" + root_text)
    return labels


def _scan_db_tokens(
    connection: sqlite3.Connection,
    tables: Iterable[str],
    needles: Set[str],
    budget_bytes: int,
    deadline: float,
) -> Tuple[Dict[str, List[str]], str]:
    """Token-scan TEXT/BLOB cells of every office table for candidate ids."""
    hits: Dict[str, List[str]] = {}
    consumed = 0
    try:
        available = _existing_tables(connection)
        for table in tables:
            if table not in available:
                return hits, "incomplete"
            columns = [
                str(row[1]) for row in connection.execute("PRAGMA table_info(" + table + ")")
            ]
            if not columns:
                return hits, "incomplete"
            quoted = ", ".join('"' + c + '"' for c in columns)
            label = table + "_text_scan"
            cursor = connection.execute("SELECT " + quoted + ' FROM "' + table + '"')
            for row_index, row in enumerate(cursor):
                if row_index >= MAX_DB_ROWS or time.monotonic() > deadline:
                    return hits, "incomplete"
                for cell in row:
                    if cell is None or isinstance(cell, (int, float)):  # noqa: UP038 — py3.8
                        continue
                    blob = cell if isinstance(cell, bytes) else str(cell).encode("utf-8")
                    consumed += len(blob)
                    if consumed > budget_bytes:
                        return hits, "incomplete"
                    _scan_blob(blob, needles, hits, label)
    except (sqlite3.Error, OSError, ValueError):
        return hits, "incomplete"
    return hits, "complete"


def _scan_blob(blob: bytes, needles: Set[str], hits: Dict[str, List[str]], label: str) -> None:
    for token in _tokens(blob):
        needle = token.decode("ascii", "ignore").lower()
        if needle in needles:
            found = hits.setdefault(needle, [])
            if label not in found:
                found.append(label)


def _scan_workspace_files(  # noqa: PLR0911 — every early exit keeps evidence conservative
    workspace: Path,
    needles: Set[str],
    budget_bytes: int,
    per_file_bytes: int,
    deadline: float,
) -> Tuple[Dict[str, List[str]], str]:
    """Bounded scan of workspace files (zip containers included) for ids."""
    hits: Dict[str, List[str]] = {}
    consumed = 0
    scanned = 0
    quarantine_root = (workspace / QUARANTINE_SUBDIR).resolve()
    try:
        for root, dirs, files in os.walk(str(workspace)):
            root_path = Path(root)
            try:
                resolved_root = root_path.resolve()
            except OSError:
                dirs[:] = []
                continue
            if resolved_root == quarantine_root or quarantine_root in resolved_root.parents:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", ".venv")]
            for name in sorted(files):
                if name in _SELF_EVIDENCE_NAMES:
                    continue
                if scanned >= MAX_SCAN_FILES or time.monotonic() > deadline:
                    return hits, "incomplete"
                path = root_path / name
                try:
                    stat_result = path.lstat()
                except OSError:
                    return hits, "incomplete"
                if not path.is_file() or path.is_symlink():
                    continue
                if stat_result.st_size > per_file_bytes:
                    continue
                label = "workspace_file:" + path.relative_to(workspace).as_posix()
                scanned += 1
                if path.suffix.lower() in _ZIP_SUFFIXES:
                    try:
                        with zipfile.ZipFile(str(path)) as archive:
                            for member in archive.infolist()[:400]:
                                if member.file_size > per_file_bytes:
                                    continue
                                blob = archive.read(member)
                                consumed += len(blob)
                                if consumed > budget_bytes:
                                    return hits, "incomplete"
                                _scan_blob(blob, needles, hits, label)
                    except (OSError, zipfile.BadZipFile, ValueError, RuntimeError):
                        return hits, "incomplete"
                    continue
                try:
                    blob = path.read_bytes()
                except OSError:
                    return hits, "incomplete"
                consumed += len(blob)
                if consumed > budget_bytes:
                    return hits, "incomplete"
                _scan_blob(blob, needles, hits, label)
    except (OSError, ValueError):
        return hits, "incomplete"
    return hits, "complete"


def collect_candidates(workspace: Path, limit: int = MAX_CANDIDATES) -> List[Path]:
    """Managed staging directories: ``<ws>/office/<doc_type>/<document_id>``."""
    root = workspace.resolve(strict=True)
    out: List[Path] = []
    for doc_type in DOC_TYPES:
        base = root / "office" / doc_type
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if entry.is_dir() and DOC_ID_RE.match(entry.name):
                out.append(entry)
                if len(out) >= limit:
                    return out
    return out


def inspect_candidate(
    database: Path, workspace: Path, doc_type: str, document_id: str
) -> Dict[str, Any]:
    """Single-candidate read-only verdict (delegates to staging_references)."""
    report = inspect_references(database, workspace, doc_type, document_id)
    report["mode"] = "quarantine_plan"
    report["safe_to_delete"] = False
    return report


def plan_quarantine(
    database: Path,
    workspace: Path,
    *,
    quiet_hours: int = DEFAULT_QUIET_HOURS,
    scan_budget_bytes: int = DEFAULT_SCAN_BUDGET_BYTES,
    scan_file_bytes: int = DEFAULT_SCAN_FILE_BYTES,
    deadline_seconds: float = 30.0,
    skip_filesystem_scan: bool = False,
) -> Dict[str, Any]:
    """Read-only classification of every managed staging directory."""
    started = _now_ms()
    quiet_ms = max(0, int(quiet_hours)) * 3600 * 1000
    notes: List[str] = []
    plan: Dict[str, Any] = {
        "read_only": True,
        "safe_to_delete": False,
        "mode": "quarantine",
        "workspace": str(workspace),
        "database": str(database),
        "candidates": [],
        "sources": [
            "office_documents.id",
            "office_documents.derived_from",
            "office_documents.workspace_path",
            "office_documents.metadata",
            "office_self_checks.doc_id",
            "office_journal_generations.output_path",
            "office_journal_generations.workspace_path",
            "office_journal_specs.spec_json",
            "office_journal_specs.template_filename",
            "office_journal_specs.workspace_path",
            "office_table_token_scan",
            "workspace_file_scan_including_zip_containers",
            "import_sentinel:" + STAGING_MARKER,
            "import_sentinel:" + COMPLETED_MARKER,
        ],
        "notes": notes,
        "quiet_hours": quiet_hours,
        "purge_requires_human_confirmation": True,
    }
    if not database.is_absolute() or not workspace.is_absolute():
        plan["error"] = "absolute_paths_required"
        return plan
    if not database.is_file() or not workspace.is_dir():
        plan["error"] = "database_or_workspace_missing"
        return plan

    root = workspace.resolve(strict=True)
    directories = collect_candidates(root)
    plan["quarantine_root"] = str(root / QUARANTINE_SUBDIR)
    # Case-insensitive needle map: a differently-cased id anywhere counts as a
    # hit for every candidate sharing that spelling. False retention is cheaper
    # than false clearance.
    needle_owners: Dict[str, List[str]] = {}
    for directory in directories:
        needle_owners.setdefault(directory.name.lower(), []).append(directory.name)
    needles = set(needle_owners)
    deadline = time.monotonic() + deadline_seconds

    exact_hits: Dict[str, List[str]] = {}
    token_hits: Dict[str, List[str]] = {}
    db_status = "complete"
    connection: Optional[sqlite3.Connection] = None
    try:
        connection = _open_ro(database)
        connection.execute("PRAGMA query_only = ON")
        tables = _existing_tables(connection)
        missing = [t for t in _REQUIRED_TABLES if t not in tables]
        if missing:
            db_status = "incomplete"
            notes.append("missing_required_tables:" + ",".join(missing))
        else:
            connection.execute("BEGIN")
            for row_index, row in enumerate(
                connection.execute(
                    "SELECT lower(id), lower(COALESCE(derived_from, '')) " "FROM office_documents"
                )
            ):
                if row_index >= MAX_DB_ROWS * 5:
                    db_status = "incomplete"
                    notes.append("office_documents_scan_limit")
                    break
                for value, label in (
                    (row[0], "document_record_including_archived"),
                    (row[1], "derived_document_lineage"),
                ):
                    for name in needle_owners.get(value, ()):
                        found = exact_hits.setdefault(name, [])
                        if label not in found:
                            found.append(label)
            for directory in directories:
                for label in _workspace_labels(
                    directory, _registered_workspaces(connection, notes)
                ):
                    found = exact_hits.setdefault(directory.name, [])
                    if label not in found:
                        found.append(label)
            if "office_journal_generations" in tables:
                for index, row in enumerate(
                    connection.execute("SELECT output_path FROM office_journal_generations")
                ):
                    if index >= MAX_DB_ROWS or time.monotonic() > deadline:
                        db_status = "incomplete"
                        notes.append("journal_scan_limit")
                        break
                    output = row[0]
                    if not isinstance(output, str) or not Path(output).is_absolute():
                        db_status = "incomplete"
                        notes.append("ambiguous_journal_path")
                        break
                    try:
                        output_path = Path(output).resolve()
                    except OSError:
                        db_status = "incomplete"
                        notes.append("unresolvable_journal_path")
                        break
                    for directory in directories:
                        resolved = directory.resolve()
                        if output_path == resolved or resolved in output_path.parents:
                            found = exact_hits.setdefault(directory.name, [])
                            if "journal_output" not in found:
                                found.append("journal_output")
            scanned, scan_state = _scan_db_tokens(
                connection, _TEXT_TABLES, needles, scan_budget_bytes, deadline
            )
            token_hits = scanned
            if scan_state != "complete":
                db_status = "incomplete"
                notes.append("db_token_scan_incomplete")
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        db_status = "incomplete"
        notes.append("database_error:" + type(exc).__name__)
    finally:
        if connection is not None:
            connection.close()

    fs_token_hits: Dict[str, List[str]] = {}
    fs_status = "skipped" if skip_filesystem_scan else "complete"
    if not skip_filesystem_scan and needles:
        fs_token_hits, fs_state = _scan_workspace_files(
            root, needles, scan_budget_bytes, scan_file_bytes, deadline
        )
        fs_status = fs_state
        if fs_state != "complete":
            notes.append("filesystem_scan_incomplete")

    now = _now_ms()
    for directory in directories:
        doc_id = directory.name
        references = list(exact_hits.get(doc_id, []))
        for labels in (token_hits, fs_token_hits):
            for label in labels.get(doc_id.lower(), []):
                if label not in references:
                    references.append(label)
        entry: Dict[str, Any] = {
            "doc_type": directory.parent.name,
            "document_id": doc_id,
            "path": directory.as_posix(),
            "references": references,
        }
        lease = _import_lease(directory, doc_id)
        entry["import_lease"] = lease
        if lease["state"] == "invalid":
            # Unreadable/oversized/foreign sentinel: retain, never infer.
            entry["status"] = "unknown"
            entry["reason"] = "import_sentinel_invalid"
            plan["candidates"].append(entry)
            continue
        if lease["active"]:
            # In-flight import, or a dead-owner import awaiting human review.
            label = "import_lease_active:" + str(lease["state"])
            if label not in references:
                references.append(label)
            entry["status"] = "referenced"
            entry["reason"] = "import_in_progress_or_pending_review"
            plan["candidates"].append(entry)
            continue
        if lease["completed"] and "import_completed_sentinel" not in references:
            references.append("import_completed_sentinel")
        try:
            resolved = directory.resolve()
            expected = root / "office" / directory.parent.name / doc_id
            if directory.is_symlink() or resolved != expected:
                entry["status"] = "unknown"
                entry["reason"] = "linked_managed_directory"
                plan["candidates"].append(entry)
                continue
            entries, total = _tree_digest(directory)
            entry["bytes"] = total
            entry["files"] = len(entries)
            entry["newest_mtime_ms"] = max((item["mtime_ms"] for item in entries), default=0)
        except (OSError, RuntimeError, ValueError) as exc:
            entry["status"] = "unknown"
            entry["reason"] = str(exc)
            plan["candidates"].append(entry)
            continue
        if references:
            entry["status"] = "referenced"
        elif db_status != "complete" or fs_status not in ("complete", "skipped"):
            entry["status"] = "unknown"
            entry["reason"] = "incomplete_reference_check"
        elif not entries:
            entry["status"] = "unknown"
            entry["reason"] = "empty_directory_not_quarantined"
        elif now - entry["newest_mtime_ms"] < quiet_ms:
            entry["status"] = "fresh"
            entry["reason"] = "modified_within_quiet_window"
        else:
            entry["status"] = "no_reference_found"
        plan["candidates"].append(entry)

    plan["db_scan_status"] = db_status
    plan["filesystem_scan_status"] = fs_status
    plan["generated_at"] = _utc(started)
    plan["duration_ms"] = _now_ms() - started
    plan["summary"] = {
        status: sum(1 for c in plan["candidates"] if c["status"] == status)
        for status in ("referenced", "no_reference_found", "unknown", "fresh")
    }
    return plan


def _new_quarantine_id(doc_type: str, doc_id: str) -> str:
    """Unique per attempt: a re-run in the same second must never collide."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return "-".join([stamp, doc_type, doc_id, str(os.getpid()), uuid.uuid4().hex[:8]])


def _finish_move(
    manifest: _Manifest, intent: Dict[str, Any], staging: Path, source: Path
) -> Dict[str, Any]:
    """Promote a verified staging copy, then remove the source safely."""
    qid = str(intent["quarantine_id"])
    final = staging.parent / qid
    files: List[Dict[str, Any]] = list(intent.get("files") or [])
    record: Dict[str, Any] = {
        "action": "done",
        "quarantine_id": qid,
        "at": _utc(_now_ms()),
        "manifest_version": MANIFEST_VERSION,
        "doc_type": intent.get("doc_type"),
        "document_id": intent.get("document_id"),
        "source_path": str(source),
        "quarantine_path": str(final),
        "bytes": intent.get("bytes", 0),
        "files": files,
        "source_removed": False,
        "eligible_for_purge_after": intent.get("eligible_for_purge_after"),
    }
    if not final.exists():
        staging.replace(final)
        _fsync_dir(final.parent)
    elif staging.exists():
        shutil.rmtree(str(staging), ignore_errors=True)
    manifest.append(record)
    if source.is_dir():
        removed, ambiguous = _remove_tree_verified(source, files)
        manifest.append(
            {
                "action": "source_removed" if removed else "needs_review",
                "quarantine_id": qid,
                "at": _utc(_now_ms()),
                "source_path": str(source),
                "ambiguous_files": ambiguous,
                "reason": None if removed else "source_changed_after_copy",
            }
        )
        record["source_removed"] = removed
        record["ambiguous_files"] = ambiguous
    else:
        record["source_removed"] = True
    return record


def _resume_incomplete(manifest: _Manifest) -> List[Dict[str, Any]]:
    """Complete or roll back interrupted moves before doing new work."""
    records = manifest.records()
    intents = [r for r in records if r.get("action") == "intent"]
    finished = {
        r.get("quarantine_id")
        for r in records
        if r.get("action") in ("done", "failed", "needs_review")
    }
    resumed: List[Dict[str, Any]] = []
    for intent in intents:
        qid = intent.get("quarantine_id")
        if not qid or qid in finished:
            continue
        staging = Path(str(intent.get("staging_path") or ""))
        source = Path(str(intent.get("source_path") or ""))
        expected = _digest_map(intent.get("files") or [])
        entry: Dict[str, Any] = {"quarantine_id": qid}
        if staging.is_dir():
            try:
                actual = _digest_map(_tree_digest(staging)[0])
            except (OSError, RuntimeError, ValueError):
                actual = {}
            if expected and actual == expected:
                _finish_move(manifest, intent, staging, source)
                entry["resumed"] = "completed"
            else:
                shutil.rmtree(str(staging), ignore_errors=True)
                manifest.append(
                    {
                        "action": "failed",
                        "quarantine_id": qid,
                        "at": _utc(_now_ms()),
                        "source_path": str(source),
                        "reason": "interrupted_partial_copy_discarded",
                    }
                )
                entry["resumed"] = "discarded_partial_copy"
        elif source.is_dir():
            manifest.append(
                {
                    "action": "failed",
                    "quarantine_id": qid,
                    "at": _utc(_now_ms()),
                    "source_path": str(source),
                    "reason": "interrupted_before_copy",
                }
            )
            entry["resumed"] = "source_intact"
        else:
            manifest.append(
                {
                    "action": "needs_review",
                    "quarantine_id": qid,
                    "at": _utc(_now_ms()),
                    "source_path": str(source),
                    "reason": "source_and_copy_both_missing",
                }
            )
            entry["resumed"] = "needs_review"
        resumed.append(entry)
    return resumed


def quarantine_run(
    database: Path,
    workspace: Path,
    *,
    dry_run: bool = True,
    quiet_hours: int = DEFAULT_QUIET_HOURS,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    scan_budget_bytes: int = DEFAULT_SCAN_BUDGET_BYTES,
    scan_file_bytes: int = DEFAULT_SCAN_FILE_BYTES,
    deadline_seconds: float = 60.0,
    skip_filesystem_scan: bool = False,
    doc_types: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Quarantine unreferenced staging directories (dry run unless asked)."""
    plan = plan_quarantine(
        database,
        workspace,
        quiet_hours=quiet_hours,
        scan_budget_bytes=scan_budget_bytes,
        scan_file_bytes=scan_file_bytes,
        deadline_seconds=deadline_seconds,
        skip_filesystem_scan=skip_filesystem_scan,
    )
    result: Dict[str, Any] = {
        "mode": "quarantine",
        "dry_run": dry_run,
        "safe_to_delete": False,
        "plan_summary": plan.get("summary"),
        "notes": list(plan.get("notes") or []),
        "planned": [],
        "quarantined": [],
        "retained": [],
        "resumed": [],
    }
    if "error" in plan:
        result["error"] = plan["error"]
        return result
    allowed = set(doc_types) if doc_types else None
    selected = [
        c
        for c in plan["candidates"]
        if c["status"] == "no_reference_found" and (allowed is None or c["doc_type"] in allowed)
    ]
    selected_ids = {id(c) for c in selected}
    result["retained"] = [
        {
            "document_id": c["document_id"],
            "doc_type": c["doc_type"],
            "status": c["status"],
            "reason": c.get("reason"),
            "references": c.get("references", [])[:5],
        }
        for c in plan["candidates"]
        if id(c) not in selected_ids
    ]
    result["planned"] = [
        {
            "document_id": c["document_id"],
            "doc_type": c["doc_type"],
            "path": c["path"],
            "bytes": c.get("bytes", 0),
            "files": c.get("files", 0),
        }
        for c in selected
    ]
    if dry_run or not selected:
        return result

    root = Path(str(plan["quarantine_root"]))
    manifest = _Manifest(root)
    stack = contextlib.ExitStack()
    try:
        stack.enter_context(_Lock(root))
    except RuntimeError as exc:
        # Another writer owns the quarantine: retain everything, retry later.
        stack.close()
        result["error"] = str(exc)
        result["notes"].append("another_quarantine_writer_active; all candidates retained")
        return result
    with stack:
        result["resumed"] = _resume_incomplete(manifest)
        for candidate in selected:
            source = Path(candidate["path"])
            qid = _new_quarantine_id(candidate["doc_type"], candidate["document_id"])
            staging = root / (qid + ".tmp-quarantine")
            entry: Dict[str, Any] = {
                "quarantine_id": qid,
                "document_id": candidate["document_id"],
                "doc_type": candidate["doc_type"],
                "source_path": str(source),
            }
            try:
                with _ExclusiveDirectory(source):
                    files, total = _tree_digest(source)
                    if not files:
                        raise RuntimeError("empty_candidate_not_quarantined")
                    intent = {
                        "action": "intent",
                        "quarantine_id": qid,
                        "at": _utc(_now_ms()),
                        "manifest_version": MANIFEST_VERSION,
                        "doc_type": candidate["doc_type"],
                        "document_id": candidate["document_id"],
                        "source_path": str(source),
                        "staging_path": str(staging),
                        "bytes": total,
                        "files": files,
                        "eligible_for_purge_after": _utc(
                            _now_ms() + int(retention_days) * 24 * 3600 * 1000
                        ),
                    }
                    manifest.append(intent)
                    _copy_tree_verified(source, staging, files)
                    after, _ = _tree_digest(source)
                    if _digest_map(after) != _digest_map(files):
                        raise RuntimeError("candidate_changed_during_copy")
                    record = _finish_move(manifest, intent, staging, source)
                entry.update(
                    {
                        "status": "quarantined",
                        "quarantine_path": record["quarantine_path"],
                        "bytes": total,
                        "files": len(files),
                        "source_removed": record.get("source_removed", False),
                        "ambiguous_files": record.get("ambiguous_files", []),
                        "eligible_for_purge_after": record["eligible_for_purge_after"],
                    }
                )
                if not record.get("source_removed", False):
                    entry["status"] = "quarantined_source_retained_for_review"
                result["quarantined"].append(entry)
            except (OSError, RuntimeError, ValueError) as exc:
                if staging.exists():
                    shutil.rmtree(str(staging), ignore_errors=True)
                manifest.append(
                    {
                        "action": "failed",
                        "quarantine_id": qid,
                        "at": _utc(_now_ms()),
                        "source_path": str(source),
                        "reason": str(exc),
                    }
                )
                entry.update({"status": "retained", "reason": str(exc)})
                result["quarantined"].append(entry)
    return result


def quarantine_report(workspace: Path) -> Dict[str, Any]:
    """Quarantine inventory: age, retention state and recoverability."""
    root = workspace.resolve(strict=True) / QUARANTINE_SUBDIR
    manifest = _Manifest(root)
    now = _now_ms()
    items: List[Dict[str, Any]] = []
    for qid, record in sorted(manifest.entries().items()):
        quarantined = Path(str(record.get("quarantine_path") or ""))
        present = quarantined.is_dir()
        eligible_after = record.get("eligible_for_purge_after")
        days_since_eligible: Optional[float] = None
        if eligible_after:
            try:
                elapsed = now - _parse_utc(eligible_after)
                days_since_eligible = round(elapsed / 86400000.0, 2)
            except (ValueError, OverflowError):
                days_since_eligible = None
        items.append(
            {
                "quarantine_id": qid,
                "document_id": record.get("document_id"),
                "doc_type": record.get("doc_type"),
                "source_path": record.get("source_path"),
                "quarantine_path": str(quarantined),
                "present": present,
                "bytes": record.get("bytes"),
                "files": len(record.get("files") or []),
                "state": record.get("action"),
                "quarantined_at": record.get("at"),
                "eligible_for_purge_after": eligible_after,
                "days_since_eligible": days_since_eligible,
                "recoverable": bool(present and record.get("action") == "done"),
            }
        )
    return {
        "quarantine_root": str(root),
        "entries": items,
        "total_entries": len(items),
        "recoverable": sum(1 for i in items if i["recoverable"]),
        "automatic_deletion": False,
        "purge_requires_human_confirmation": True,
    }


def restore_entry(  # noqa: PLR0911 — guard clauses keep every refusal explicit
    workspace: Path, quarantine_id: str
) -> Dict[str, Any]:
    """Copy quarantined bytes back to the original path and verify hashes."""
    root = workspace.resolve(strict=True) / QUARANTINE_SUBDIR
    manifest = _Manifest(root)
    record = manifest.entries().get(quarantine_id)
    out: Dict[str, Any] = {"quarantine_id": quarantine_id}
    if record is None:
        out.update(status="error", error="unknown_quarantine_id")
        return out
    if record.get("action") != "done":
        out.update(status="error", error="not_restorable:" + str(record.get("action")))
        return out
    source = Path(str(record["source_path"]))
    quarantined = Path(str(record["quarantine_path"]))
    if not quarantined.is_dir():
        out.update(status="error", error="quarantine_copy_missing")
        return out
    if source.exists():
        out.update(status="error", error="original_path_occupied")
        return out
    expected = list(record.get("files") or [])
    if not expected:
        out.update(status="error", error="manifest_has_no_file_records")
        return out
    with _Lock(root):
        try:
            source.parent.mkdir(parents=True, exist_ok=True)
            _copy_tree_verified(quarantined, source, expected)
            actual, total = _tree_digest(source)
            if _digest_map(actual) != _digest_map(expected):
                raise RuntimeError("restore_verification_failed")
            shutil.rmtree(str(quarantined))
            manifest.append(
                {
                    "action": "restored",
                    "quarantine_id": quarantine_id,
                    "at": _utc(_now_ms()),
                    "restored_to": str(source),
                    "bytes": total,
                }
            )
        except (OSError, RuntimeError, ValueError) as exc:
            manifest.append(
                {
                    "action": "restore_failed",
                    "quarantine_id": quarantine_id,
                    "at": _utc(_now_ms()),
                    "reason": str(exc),
                }
            )
            out.update(status="error", error=str(exc))
            return out
    out.update(status="restored", restored_to=str(source))
    return out


def purge_entry(  # noqa: PLR0911 — guard clauses keep every refusal explicit
    workspace: Path,
    quarantine_id: str,
    *,
    confirmed_id: str,
    allow_permanent_deletion: bool = False,
) -> Dict[str, Any]:
    """Permanent deletion of one entry — explicit, confirmed, retention-gated."""
    out: Dict[str, Any] = {"quarantine_id": quarantine_id}
    if not allow_permanent_deletion:
        out.update(status="refused", error="permanent_deletion_not_allowed")
        return out
    if confirmed_id != quarantine_id:
        out.update(status="refused", error="confirmation_id_mismatch")
        return out
    root = workspace.resolve(strict=True) / QUARANTINE_SUBDIR
    manifest = _Manifest(root)
    record = manifest.entries().get(quarantine_id)
    if record is None or record.get("action") != "done":
        out.update(status="refused", error="unknown_or_not_purgeable_entry")
        return out
    eligible = record.get("eligible_for_purge_after")
    if not eligible:
        out.update(status="refused", error="missing_retention_marker")
        return out
    try:
        if _now_ms() < _parse_utc(eligible):
            out.update(status="refused", error="retention_window_not_elapsed")
            return out
    except (ValueError, OverflowError):
        out.update(status="refused", error="unparseable_retention_marker")
        return out
    target = Path(str(record["quarantine_path"]))
    if not target.is_dir():
        out.update(status="refused", error="quarantine_copy_missing")
        return out
    try:
        if root.resolve() not in target.resolve().parents:
            out.update(status="refused", error="target_outside_quarantine_root")
            return out
    except OSError:
        out.update(status="refused", error="target_unresolvable")
        return out
    with _Lock(root):
        shutil.rmtree(str(target))
        manifest.append(
            {
                "action": "purged",
                "quarantine_id": quarantine_id,
                "at": _utc(_now_ms()),
                "purge_confirmed_id": confirmed_id,
                "bytes": record.get("bytes"),
            }
        )
    out.update(status="purged", bytes_freed=record.get("bytes"))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--database", type=Path, required=True)
    common.add_argument("--workspace", type=Path, required=True)
    common.add_argument("--quiet-hours", type=int, default=DEFAULT_QUIET_HOURS)
    common.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    common.add_argument("--skip-filesystem-scan", action="store_true")

    sub.add_parser("plan", parents=[common], help="read-only classification")
    quarantine_cmd = sub.add_parser(
        "quarantine", parents=[common], help="move unreferenced staging into quarantine"
    )
    quarantine_cmd.add_argument(
        "--execute", action="store_true", help="move files (default: dry run)"
    )
    quarantine_cmd.add_argument("--doc-type", action="append", choices=list(DOC_TYPES))
    report_cmd = sub.add_parser("report", help="list quarantine entries")
    report_cmd.add_argument("--workspace", type=Path, required=True)
    restore_cmd = sub.add_parser("restore", help="restore one quarantined entry")
    restore_cmd.add_argument("--workspace", type=Path, required=True)
    restore_cmd.add_argument("--quarantine-id", required=True)
    purge_cmd = sub.add_parser("purge", help="permanent deletion (explicit only)")
    purge_cmd.add_argument("--workspace", type=Path, required=True)
    purge_cmd.add_argument("--quarantine-id", required=True)
    purge_cmd.add_argument("--confirm-id", required=True)
    purge_cmd.add_argument("--allow-permanent-deletion", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "plan":
        report = plan_quarantine(
            args.database,
            args.workspace,
            quiet_hours=args.quiet_hours,
            skip_filesystem_scan=args.skip_filesystem_scan,
        )
    elif args.command == "quarantine":
        report = quarantine_run(
            args.database,
            args.workspace,
            dry_run=not args.execute,
            quiet_hours=args.quiet_hours,
            retention_days=args.retention_days,
            skip_filesystem_scan=args.skip_filesystem_scan,
            doc_types=args.doc_type,
        )
    elif args.command == "report":
        report = quarantine_report(args.workspace)
    elif args.command == "restore":
        report = restore_entry(args.workspace, args.quarantine_id)
    else:
        report = purge_entry(
            args.workspace,
            args.quarantine_id,
            confirmed_id=args.confirm_id,
            allow_permanent_deletion=args.allow_permanent_deletion,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))  # noqa: T201 -- CLI JSON output
    if isinstance(report, dict) and (
        report.get("error") or report.get("status") in ("error", "refused")
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
