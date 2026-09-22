"""Unit tests for backend/services/arena_keystore.py (plan §1.3-A / D6).

Regression target: the spec originally derived the Fernet key from
SAGE_LOCAL_AUTH_TOKEN, which is regenerated per backend start — every stored
password would have been orphaned after a restart.
"""

import base64
import os
import stat
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from backend.services import arena_keystore as ks
from backend.services.arena_accounts import ArenaAccountService


def test_master_key_created_once_and_stable(tmp_path):
    first = ks.load_or_create_master_key(str(tmp_path))
    path = tmp_path / ks.MASTER_KEY_FILE
    assert path.is_file()
    assert ks.load_or_create_master_key(str(tmp_path)) == first
    assert len(base64.urlsafe_b64decode(first.encode())) == 32


def test_master_key_file_permissions(tmp_path):
    ks.load_or_create_master_key(str(tmp_path))
    path = tmp_path / ks.MASTER_KEY_FILE
    mode = path.stat().st_mode
    if os.name == "nt":
        # Windows maps os.chmod onto the readonly attribute only (observed mode
        # is 0o666), so the real protection is the file living under the
        # per-user profile; DPAPI wrapping is tracked as future hardening.
        assert path.is_file()
        assert path.stat().st_size > 0
    else:
        assert stat.S_IMODE(mode) == 0o600


def test_empty_master_key_file_is_regenerated(tmp_path):
    path = tmp_path / ks.MASTER_KEY_FILE
    path.write_text("", encoding="ascii")
    value = ks.load_or_create_master_key(str(tmp_path))
    assert value
    assert path.read_text(encoding="ascii") == value


def test_unreadable_master_key_raises(tmp_path):
    (tmp_path / ks.MASTER_KEY_FILE).mkdir()  # a directory cannot be read as a file
    with pytest.raises(ks.ArenaKeystoreError):
        ks.load_or_create_master_key(str(tmp_path))


def test_fernet_key_is_valid_and_stable(tmp_path, monkeypatch):
    monkeypatch.setattr(ks, "machine_id", lambda: "machine-fixed")
    k1 = ks.arena_fernet_key(str(tmp_path))
    assert ks.arena_fernet_key(str(tmp_path)) == k1
    fernet = Fernet(k1)
    assert fernet.decrypt(fernet.encrypt(b"hunter2")) == b"hunter2"


def test_fernet_key_changes_with_machine_id(tmp_path, monkeypatch):
    """Same master key on another machine must NOT decrypt (documented R5 risk)."""
    monkeypatch.setattr(ks, "machine_id", lambda: "machine-a")
    ka = ks.arena_fernet_key(str(tmp_path))
    monkeypatch.setattr(ks, "machine_id", lambda: "machine-b")
    assert ks.arena_fernet_key(str(tmp_path)) != ka


def test_data_dir_resolution_order(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit"
    assert ks.arena_data_dir(str(explicit)) == explicit
    monkeypatch.delenv("SAGE_USER_DATA_DIR", raising=False)
    assert ks.arena_data_dir() == Path("backend/data") / "arena"
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path / "sage"))
    assert ks.arena_data_dir() == tmp_path / "sage" / "arena"
    assert ks.master_key_path() == tmp_path / "sage" / "arena" / ks.MASTER_KEY_FILE
    assert ks.arena_db_path(str(explicit)) == explicit / ks.ARENA_DB_FILE


def test_credentials_survive_backend_restart(tmp_path, monkeypatch):
    """The actual P0 bug: restart must not orphan stored secrets."""
    monkeypatch.setattr(ks, "machine_id", lambda: "machine-fixed")
    db = str(tmp_path / ks.ARENA_DB_FILE)

    first = ArenaAccountService(db_path=db, encryption_key=ks.arena_fernet_key(str(tmp_path)))
    acc = first.create_account(email="a@example.com", password="hunter2")
    first.close()

    second = ArenaAccountService(db_path=db, encryption_key=ks.arena_fernet_key(str(tmp_path)))
    try:
        assert second.get_secret(acc["id"]) == "hunter2"
        assert second.credentials_readable() is True
    finally:
        second.close()
