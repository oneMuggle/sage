import os
import tempfile
import pytest
from cryptography.fernet import Fernet

from backend.services.arena_accounts import (
    ArenaAccountService, AccountState,
)


@pytest.fixture
def svc():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    key = Fernet.generate_key()
    s = ArenaAccountService(db_path=path, encryption_key=key)
    yield s
    os.unlink(path)


def test_create_account_round_trip(svc):
    acc = svc.create_account(email="user@example.com", password="hunter2")
    assert acc["email"] == "user@example.com"
    fetched = svc.get_account(acc["id"])
    assert fetched["password"] == "hunter2"
    assert fetched["state"] == AccountState.AVAILABLE.value


def test_create_account_rejects_duplicate_email(svc):
    svc.create_account(email="dup@example.com", password="x")
    with pytest.raises(ValueError, match="already exists"):
        svc.create_account(email="dup@example.com", password="y")


def test_reserve_picks_least_recently_used(svc):
    a1 = svc.create_account(email="a@example.com", password="x")
    a2 = svc.create_account(email="b@example.com", password="y")
    # Manually advance a1's last_used_at
    svc._conn.execute(
        "UPDATE arena_accounts SET last_used_at = ? WHERE id = ?",
        ("2026-01-01T00:00:00", a1["id"]),
    )
    svc._conn.commit()
    picked = svc.reserve_account()
    assert picked["id"] == a1["id"]


def test_record_failure_isolates_after_threshold(svc):
    acc = svc.create_account(email="fail@example.com", password="x")
    for i in range(3):
        svc.record_failure(acc["id"], reason="timeout")
    final = svc.get_account(acc["id"])
    assert final["state"] == AccountState.DISABLED.value


def test_release_resets_failure_count(svc):
    acc = svc.create_account(email="rel@example.com", password="x")
    svc.record_failure(acc["id"], reason="x")
    svc.record_failure(acc["id"], reason="x")
    svc.release_account(acc["id"])
    # After release, count should be back to 0
    fresh = svc.get_account(acc["id"])
    assert fresh["failure_count"] == 0
    assert fresh["state"] == AccountState.AVAILABLE.value


def test_enable_account_from_disabled(svc):
    acc = svc.create_account(email="en@example.com", password="x")
    for _ in range(3):
        svc.record_failure(acc["id"], reason="x")
    svc.enable_account(acc["id"])
    fresh = svc.get_account(acc["id"])
    assert fresh["state"] == AccountState.AVAILABLE.value


def test_soft_delete_sets_destroyed(svc):
    acc = svc.create_account(email="del@example.com", password="x")
    svc.soft_delete_account(acc["id"])
    final = svc.get_account(acc["id"])
    assert final["state"] == AccountState.DESTROYED.value
