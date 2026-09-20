import contextlib
import os
import tempfile

import pytest
from cryptography.fernet import Fernet

from backend.services.arena_accounts import (
    AccountState,
    ArenaAccountService,
)


@pytest.fixture()
def svc():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    key = Fernet.generate_key()
    s = ArenaAccountService(db_path=path, encryption_key=key)
    yield s
    s.close()  # Windows：连接未关闭时 unlink 报 WinError 32
    with contextlib.suppress(PermissionError):
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
    svc.create_account(email="b@example.com", password="y")  # second account, not used directly
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
    for _ in range(3):
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


def test_derive_arena_key_is_stable_and_fernet_compatible():
    """SPEC-GAP-01 regression: PBKDF2 derivation produces stable Fernet keys."""
    from cryptography.fernet import Fernet

    from backend.services.arena_accounts import derive_arena_key

    k1 = derive_arena_key(token="shared-token", machine_id="machine-abc")
    k2 = derive_arena_key(token="shared-token", machine_id="machine-abc")
    assert k1 == k2
    # Different inputs → different keys
    k3 = derive_arena_key(token="other", machine_id="machine-abc")
    assert k1 != k3
    # Fernet must accept the derived key
    Fernet(k1)


# ---------------------------------------------------------------------------
# 主密钥托管（SecretBox 包装，preferences 落库；2026-09-19）
# ---------------------------------------------------------------------------

class _FakeSettingsRepo:
    def __init__(self):
        self.store: dict = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, value_type="string", category="general"):
        self.store[key] = value


def test_get_or_create_master_key_round_trip(monkeypatch):
    monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")
    from backend.services.arena_accounts import (
        MASTER_KEY_PREFERENCE,
        get_or_create_master_key,
    )

    repo = _FakeSettingsRepo()
    key1 = get_or_create_master_key(repo)
    assert repo.store[MASTER_KEY_PREFERENCE].startswith("enc:test:")
    key2 = get_or_create_master_key(repo)
    assert key1 == key2  # 二次读取复用，不重新生成


def test_get_or_create_master_key_regenerates_on_unwrap_failure(monkeypatch):
    monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")
    from backend.services.arena_accounts import get_or_create_master_key

    repo = _FakeSettingsRepo()
    repo.set("arena_master_key", "enc:test:v1:bm90LWEta2V5")  # 损坏载荷
    key = get_or_create_master_key(repo)
    assert key  # 解包失败 → 重新生成而非拒绝启动
    assert get_or_create_master_key(repo) == key
