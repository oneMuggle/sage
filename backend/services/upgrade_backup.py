"""Pinned SQLite recovery point, created before schema initialization (Python 3.8)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional


def installed_build_identity() -> str:
    """Packaged provenance first; source checkout package version otherwise."""
    root = Path(__file__).resolve().parents[2]
    for name in ("build-manifest.json", "package.json"):
        candidate = root / name
        if candidate.is_file():
            metadata = json.loads(candidate.read_text(encoding="utf-8-sig"))
            version = metadata.get("version")
            if not isinstance(version, str) or not version.strip():
                raise RuntimeError("Cannot identify build for pre-upgrade backup")
            return ":".join((version, str(metadata.get("commit", "source")), str(metadata.get("buildId", "source"))))
    raise RuntimeError("Build identity missing; refusing database initialization without a recovery point")


def _validate_snapshot(path: Path) -> None:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if conn.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RuntimeError("Invalid pre-upgrade snapshot: " + str(path))
    finally:
        conn.close()  # sqlite context managers do not close handles (Windows rename).


def ensure_upgrade_backup(db_path: str, build_id: str) -> Optional[Path]:
    """Fail closed on backup errors. Snapshots are excluded from daily rotation.

    A fixed build identity prevents retries from overwriting the pre-migration
    copy. This protects SQLite only, not attachment directories or credentials.
    """
    if db_path == ":memory:":
        return None
    source = Path(db_path)
    if not source.exists() or source.stat().st_size == 0:
        return None  # first install, nothing to migrate
    if not build_id.strip():
        raise ValueError("Missing build identity")
    directory = source.parent / "upgrade-backups"
    directory.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256((source.name + "\0" + build_id).encode("utf-8")).hexdigest()[:32]
    target = directory / ("pre-upgrade-" + identity + ".db")
    if target.exists():
        _validate_snapshot(target)
        return target
    lock = directory / (".pre-upgrade-" + identity + ".lock")
    try:
        lock.mkdir()  # exclusive across processes; a stale lock requires admin review
    except FileExistsError as exc:
        raise RuntimeError("Pre-upgrade backup in progress or interrupted: " + str(lock)) from exc
    temporary = directory / (".pre-upgrade-" + identity + ".tmp")
    deadline = time.monotonic() + 30

    def progress(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() > deadline:
            raise TimeoutError("Pre-upgrade backup exceeded 30 seconds; migration not started")

    try:
        if target.exists():
            _validate_snapshot(target)
            return target
        src = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            dst = sqlite3.connect(str(temporary))
            try:
                src.backup(dst, pages=256, progress=progress, sleep=0.05)
            finally:
                dst.close()
        finally:
            src.close()
        _validate_snapshot(temporary)
        temporary.replace(target)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Pre-upgrade backup failed; database migration blocked: " + str(directory)) from exc
    finally:
        lock.rmdir()
    return target
