"""``BashSessionStore`` 持久化仓储单元测试（2026-11-06 Phase 2）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.data.database import Database
from backend.tools.bash_session_persistence import (
    BashSessionStore,
    _identity_from_json,
    _identity_to_json,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def store(tmp_path: Path) -> BashSessionStore:
    return BashSessionStore(Database(str(tmp_path / "persist.db")))


def _session(**overrides):
    values = {
        "shell_id": "sh-1",
        "process": SimpleNamespace(pid=1234),
        "process_group_id": 1234,
        "command": "pytest -q",
        "stdout_path": "/tmp/out",
        "stderr_path": "/tmp/err",
        "stdout_identity": (10, 20),
        "stderr_identity": (10, 21),
        "stdout_offset": 5,
        "stderr_offset": 6,
        "start_token": "boot:12345",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestBashSessionStore:
    def test_persist_then_list_all(self, store: BashSessionStore) -> None:
        session = _session()
        store.persist(session)
        records = store.list_all()
        assert len(records) == 1
        rec = records[0]
        assert rec.shell_id == "sh-1"
        assert rec.pid == 1234
        assert rec.pgid == 1234
        assert rec.command == "pytest -q"
        assert rec.stdout_identity == (10, 20)
        assert rec.stderr_identity == (10, 21)
        assert rec.stdout_offset == 5
        assert rec.stderr_offset == 6
        assert rec.start_token == "boot:12345"
        assert rec.started_at > 0

    def test_persist_is_upsert(self, store: BashSessionStore) -> None:
        store.persist(_session(stdout_offset=5))
        store.persist(_session(stdout_offset=99))
        records = store.list_all()
        assert len(records) == 1
        assert records[0].stdout_offset == 99

    def test_update_offsets(self, store: BashSessionStore) -> None:
        store.persist(_session())
        store.update_offsets("sh-1", 1024, 2048)
        rec = store.list_all()[0]
        assert rec.stdout_offset == 1024
        assert rec.stderr_offset == 2048

    def test_remove(self, store: BashSessionStore) -> None:
        store.persist(_session())
        store.remove("sh-1")
        assert store.list_all() == []

    def test_remove_unknown_is_noop(self, store: BashSessionStore) -> None:
        store.remove("missing")
        assert store.list_all() == []

    def test_identity_json_roundtrip(self) -> None:
        assert _identity_to_json((1, 2)) == "[1, 2]"
        assert _identity_from_json("[1, 2]") == (1, 2)
        assert _identity_to_json(None) is None
        assert _identity_from_json(None) is None
        assert _identity_from_json("broken") is None

    def test_migrates_legacy_schema_without_start_token(self, tmp_path: Path) -> None:
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE bash_sessions (
                shell_id TEXT PRIMARY KEY,
                pid INTEGER NOT NULL,
                pgid INTEGER NOT NULL,
                command TEXT NOT NULL,
                stdout_path TEXT NOT NULL,
                stderr_path TEXT NOT NULL,
                stdout_identity TEXT,
                stderr_identity TEXT,
                stdout_offset INTEGER NOT NULL DEFAULT 0,
                stderr_offset INTEGER NOT NULL DEFAULT 0,
                started_at INTEGER NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()

        store = BashSessionStore(Database(str(db_path)))
        store.persist(_session())
        assert store.list_all()[0].start_token == "boot:12345"
