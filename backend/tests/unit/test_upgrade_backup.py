"""Pre-migration snapshots survive daily rotation and startup retries."""
import ast
import sqlite3
from pathlib import Path

import pytest

from backend.services.upgrade_backup import ensure_upgrade_backup

pytestmark = pytest.mark.unit


def seed(path):
    with sqlite3.connect(str(path)) as conn:
        conn.execute("CREATE TABLE original (value TEXT)")
        conn.execute("INSERT INTO original VALUES ('before')")


def test_snapshot_is_pinned_and_not_overwritten(tmp_path):
    db = tmp_path / "sage.db"
    seed(db)
    snapshot = ensure_upgrade_backup(str(db), "version-1")
    assert snapshot.parent.name == "upgrade-backups"
    with sqlite3.connect(str(db)) as conn:
        conn.execute("ALTER TABLE original ADD COLUMN added TEXT")
    assert ensure_upgrade_backup(str(db), "version-1") == snapshot
    with sqlite3.connect(str(snapshot)) as conn:
        assert len(conn.execute("PRAGMA table_info(original)").fetchall()) == 1
        assert conn.execute("SELECT value FROM original").fetchone() == ("before",)
    assert ensure_upgrade_backup(str(db), "version-2") != snapshot


def test_first_install_and_memory_do_not_create_empty_snapshots(tmp_path):
    assert ensure_upgrade_backup(str(tmp_path / "new.db"), "v1") is None
    assert ensure_upgrade_backup(":memory:", "v1") is None
    assert not (tmp_path / "new.db").exists()


def test_corrupt_source_blocks_upgrade(tmp_path):
    db = tmp_path / "sage.db"
    db.write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="migration blocked"):
        ensure_upgrade_backup(str(db), "v1")
    assert not list((tmp_path / "upgrade-backups").glob("*.db"))


def test_corrupt_existing_snapshot_is_not_overwritten(tmp_path):
    db = tmp_path / "sage.db"
    seed(db)
    snapshot = ensure_upgrade_backup(str(db), "v1")
    snapshot.write_bytes(b"corrupt")
    with pytest.raises(sqlite3.DatabaseError):
        ensure_upgrade_backup(str(db), "v1")
    assert snapshot.read_bytes() == b"corrupt"


def test_snapshot_includes_wal_data(tmp_path):
    db = tmp_path / "sage.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE t (x)")
        conn.execute("INSERT INTO t VALUES (42)")
        conn.commit()
        snapshot = ensure_upgrade_backup(str(db), "v1")
        with sqlite3.connect(str(snapshot)) as saved:
            assert saved.execute("SELECT x FROM t").fetchone() == (42,)
    finally:
        conn.close()


def test_upgrade_backup_precedes_init_db_in_lifespan():
    source = Path(__file__).resolve().parents[2] / "main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    lifespan = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan")
    calls = sorted((n.lineno, ast.dump(n.func)) for n in ast.walk(lifespan) if isinstance(n, ast.Call))
    backup = next(line for line, func in calls if "id='ensure_upgrade_backup'" in func)
    init = next(line for line, func in calls if "attr='init_db'" in func)
    assert backup < init


def test_daily_rotation_cannot_remove_upgrade_snapshot(tmp_path):
    from backend.services.backup_service import create_backup

    db = tmp_path / "sage.db"
    seed(db)
    snapshot = ensure_upgrade_backup(str(db), "v1")
    import os

    from backend.services.backup_service import list_backups

    for day in range(9):
        entry = create_backup(reason="daily", db_path=str(db))
        assert entry is not None
        # Model distinct daily mtimes, not same-clock-tick manual backups.
        os.utime(tmp_path / "backups" / entry["name"], (1000 + day, 1000 + day))
    assert len(list_backups(str(db))) == 7
    assert snapshot.is_file()


def test_write_failure_blocks_migration_and_releases_lock(tmp_path, monkeypatch):
    db = tmp_path / "sage.db"
    seed(db)

    def fail_replace(self, target):
        raise PermissionError("disk unavailable")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(RuntimeError, match="migration blocked"):
        ensure_upgrade_backup(str(db), "v1")
    assert not list((tmp_path / "upgrade-backups").iterdir())
    with sqlite3.connect(str(db)) as conn:
        assert conn.execute("SELECT value FROM original").fetchone() == ("before",)


def test_stale_lock_blocks_backup_without_overwriting_source(tmp_path):
    import hashlib

    db = tmp_path / "sage.db"
    seed(db)
    directory = tmp_path / "upgrade-backups"
    directory.mkdir()
    identity = hashlib.sha256(b"sage.db\0v1").hexdigest()[:32]
    lock = directory / (".pre-upgrade-" + identity + ".lock")
    lock.mkdir()
    with pytest.raises(RuntimeError, match="interrupted"):
        ensure_upgrade_backup(str(db), "v1")
    assert lock.is_dir()
    assert not list(directory.glob("*.db"))


def test_build_identity_uses_bom_manifest_and_distinguishes_rebuilds(tmp_path, monkeypatch):
    import json

    from backend.services import upgrade_backup

    monkeypatch.setattr(upgrade_backup, "__file__", str(tmp_path / "backend/services/upgrade_backup.py"))
    manifest = tmp_path / "build-manifest.json"
    manifest.write_text(json.dumps({"version": "v1", "commit": "abc", "buildId": "one"}), encoding="utf-8-sig")
    first = upgrade_backup.installed_build_identity()
    manifest.write_text(json.dumps({"version": "v1", "commit": "abc", "buildId": "two"}), encoding="utf-8-sig")
    assert upgrade_backup.installed_build_identity() != first
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="identify build"):
        upgrade_backup.installed_build_identity()
