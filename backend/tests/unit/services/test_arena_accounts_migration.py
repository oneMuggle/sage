"""Schema migration + secret-projection tests for ArenaAccountService.

Covers plan §5.3 (additive migrations for pre-port databases) and §1.3-C
(secrets are opt-in, and a lost master key degrades instead of exploding).
"""

import sqlite3

import pytest
from cryptography.fernet import Fernet

from backend.services.arena_accounts import (
    ArenaAccountService,
    ArenaCredentialError,
)

#: The table as it shipped before the ArenCard port (pool bookkeeping only).
_LEGACY_SCHEMA = """
CREATE TABLE arena_accounts (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_enc  BLOB NOT NULL,
    state         TEXT NOT NULL DEFAULT 'available',
    last_used_at  TEXT,
    failure_count INTEGER NOT NULL DEFAULT 0,
    isolated_at   TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    notes         TEXT
);
"""

_NEW_COLUMNS = (
    "proxy_url",
    "proxy_sid",
    "exit_ip",
    "credits",
    "user_id",
    "last_draw_at",
    "draw_count",
    "source",
)


def _legacy_db(path: str, key: bytes) -> None:
    fernet = Fernet(key)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO arena_accounts (id, email, password_enc, state, "
            "failure_count, created_at, updated_at, notes) "
            "VALUES ('legacy-1', 'old@example.com', ?, 'available', 0, "
            "'2026-01-01T00:00:00', '2026-01-01T00:00:00', 'pre-port')",
            (fernet.encrypt(b"hunter2"),),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def migrated(tmp_path):
    key = Fernet.generate_key()
    db = str(tmp_path / "arena.sqlite")
    _legacy_db(db, key)
    svc = ArenaAccountService(db_path=db, encryption_key=key)
    yield svc
    svc.close()


def test_legacy_db_is_migrated_in_place(migrated):
    acc = migrated.get_account("legacy-1", include_secret=True)
    assert acc["password"] == "hunter2"
    assert acc["notes"] == "pre-port"  # pre-existing data untouched
    for column in _NEW_COLUMNS:
        assert column in acc
    assert acc["draw_count"] == 0
    assert acc["proxy_url"] is None
    # idempotent
    migrated._migrate_schema()
    assert migrated.get_account("legacy-1")["email"] == "old@example.com"


def test_fresh_db_has_all_columns(tmp_path):
    svc = ArenaAccountService(
        db_path=str(tmp_path / "fresh.sqlite"), encryption_key=Fernet.generate_key()
    )
    try:
        columns = {row[1] for row in svc._conn.execute("PRAGMA table_info(arena_accounts)")}
        for column in _NEW_COLUMNS:
            assert column in columns
        tables = {
            row[0]
            for row in svc._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "arena_draws" in tables
    finally:
        svc.close()


def test_binding_credits_and_draw_history(migrated):
    migrated.update_binding(
        "legacy-1", "http://u:p@1.2.3.4:8080", proxy_sid="sid-1", exit_ip="1.2.3.4"
    )
    migrated.update_credits("legacy-1", 500, user_id="user-1")
    draw_id = migrated.record_draw(
        "legacy-1",
        {
            "model": "gpt-x",
            "internal": "gpt-x-2026",
            "provider": "openai",
            "tier": "high",
            "reasoning_tokens": 1234,
            "input_tokens": 10,
            "output_tokens": 20,
            "session_id": "s-1",
            "run_id": "r-1",
            "kept": True,
            "miss_action": None,
        },
    )
    rows = migrated.list_draws(account_id="legacy-1")
    assert len(rows) == 1
    assert rows[0]["id"] == draw_id
    assert rows[0]["kept"] is True
    assert rows[0]["reasoning_tokens"] == 1234
    assert rows[0]["model"] == "gpt-x"

    acc = migrated.get_account("legacy-1")
    assert acc["exit_ip"] == "1.2.3.4"
    assert acc["credits"] == 500
    assert acc["user_id"] == "user-1"
    assert acc["draw_count"] == 1
    assert acc["last_draw_at"]

    migrated.record_draw("legacy-1", {"model": "other", "kept": False, "miss_action": "archive"})
    assert migrated.get_account("legacy-1")["draw_count"] == 2
    newest = migrated.list_draws(account_id="legacy-1", limit=1)[0]
    assert newest["kept"] is False
    assert newest["miss_action"] == "archive"


def test_secrets_are_absent_from_default_projections(tmp_path):
    svc = ArenaAccountService(
        db_path=str(tmp_path / "a.sqlite"), encryption_key=Fernet.generate_key()
    )
    try:
        created = svc.create_account(email="n@example.com", password="sekret")
        assert "password" not in created
        assert "password" not in svc.get_account(created["id"])
        assert all("password" not in a for a in svc.list_accounts())
        assert "password" not in svc.reserve_account()
        assert svc.get_secret(created["id"]) == "sekret"
        assert svc.get_secret("does-not-exist") is None
    finally:
        svc.close()


def test_wrong_key_raises_credential_error_but_public_reads_work(tmp_path):
    db = str(tmp_path / "arena.sqlite")
    _legacy_db(db, Fernet.generate_key())
    foreign = ArenaAccountService(db_path=db, encryption_key=Fernet.generate_key())
    try:
        assert foreign.credentials_readable() is False
        with pytest.raises(ArenaCredentialError):
            foreign.get_account("legacy-1", include_secret=True)
        with pytest.raises(ArenaCredentialError):
            foreign.get_secret("legacy-1")
        # The account list must keep working so the UI can explain the problem.
        assert foreign.list_accounts()[0]["email"] == "old@example.com"
        assert foreign.count_accounts() == 1
    finally:
        foreign.close()


def test_credentials_readable_true_when_empty(tmp_path):
    svc = ArenaAccountService(
        db_path=str(tmp_path / "empty.sqlite"), encryption_key=Fernet.generate_key()
    )
    try:
        assert svc.credentials_readable() is True
        assert svc.count_accounts() == 0
    finally:
        svc.close()
