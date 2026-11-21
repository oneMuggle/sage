# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""浏览器多账号单元测试（方案 2026-11-20 browser-multi-account）。

覆盖：
- credential_vault 多账号 key 维度（save/load/list/delete/find 按账号隔离）
- BrowserAccountService 注册表 CRUD（含唯一约束 / 默认账号唯一）
- ensure_legacy_accounts 懒迁移（平铺 vault 凭据 → 默认账号）
"""

from __future__ import annotations

import pytest

from backend.services.browser_account_service import BrowserAccountService
from backend.tools.credential_vault import (
    delete_credential,
    find_credential_for_host,
    list_credentials,
    load_credential,
    load_storage_origins,
    save_credential,
    save_storage_state,
    split_vault_key,
    vault_key,
)

<<<<<<< HEAD
pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("_online_network_settings")]
=======
pytestmark = [pytest.mark.unit]
>>>>>>> origin/main

_COOKIES_A = [
    {"name": "SID", "value": "acct-a", "domain": ".example.com", "path": "/", "sameSite": "Lax"},
]
_COOKIES_B = [
    {"name": "SID", "value": "acct-b", "domain": ".example.com", "path": "/", "sameSite": "Lax"},
]


@pytest.fixture(autouse=True)
def _force_test_secret_scheme(monkeypatch):
    """enc: 加解密走确定性 test 方案（base64），保证 CI 可复现。"""
    monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")


@pytest.fixture()
def repo():
    from backend.data.settings_repo import SettingsRepository

    return SettingsRepository()


# ── vault key helpers ─────────────────────────────────────────


def test_vault_key_default_and_named():
    assert vault_key(".cnki.net") == ".cnki.net"
    assert vault_key(".cnki.net", "default") == ".cnki.net"
    assert vault_key(".cnki.net", "acc-1") == ".cnki.net::acc-1"


def test_split_vault_key_roundtrip():
    assert split_vault_key(".cnki.net") == (".cnki.net", None)
    assert split_vault_key(".cnki.net::acc-1") == (".cnki.net", "acc-1")


# ── vault 多账号隔离 ───────────────────────────────────────────


def test_save_load_isolated_per_account(repo):
    save_credential(".example.com", _COOKIES_A, repo=repo)
    save_credential(".example.com", _COOKIES_B, repo=repo, account_id="acc-b")

    default = load_credential(".example.com", repo=repo)
    named = load_credential(".example.com", repo=repo, account_id="acc-b")

    assert default[0]["value"] == "acct-a"
    assert named[0]["value"] == "acct-b"
    # 两个账号互不覆盖
    assert default[0]["value"] != named[0]["value"]


def test_list_credentials_exposes_account_id(repo):
    save_credential(".example.com", _COOKIES_A, repo=repo)
    save_credential(".example.com", _COOKIES_B, repo=repo, account_id="acc-b")
    records = {r["account_id"]: r for r in list_credentials(repo=repo)}

    assert None in records
    assert "acc-b" in records
    assert records[None]["domain"] == ".example.com"
    assert records["acc-b"]["domain"] == ".example.com"
    # 不回显值
    assert "cookies" not in records["acc-b"]


def test_delete_credential_per_account(repo):
    save_credential(".example.com", _COOKIES_A, repo=repo)
    save_credential(".example.com", _COOKIES_B, repo=repo, account_id="acc-b")

    assert delete_credential(".example.com", repo=repo, account_id="acc-b") is True
    assert load_credential(".example.com", repo=repo, account_id="acc-b") is None
    # 默认账号不受影响
    assert load_credential(".example.com", repo=repo)[0]["value"] == "acct-a"


def test_find_credential_for_host_account_filter(repo):
    save_credential(".example.com", _COOKIES_A, repo=repo)
    save_credential(".example.com", _COOKIES_B, repo=repo, account_id="acc-b")

    assert find_credential_for_host("www.example.com", repo=repo) == ".example.com"
    assert (
        find_credential_for_host("www.example.com", repo=repo, account_id="acc-b")
        == ".example.com"
    )
    # 未登记的账号 → 无匹配
    assert find_credential_for_host("www.example.com", repo=repo, account_id="acc-x") is None


def test_storage_state_isolated_per_account(repo):
    origins_a = [{"origin": "https://www.example.com", "localStorage": {"k": "a"}}]
    origins_b = [{"origin": "https://www.example.com", "localStorage": {"k": "b"}}]
    save_storage_state(".example.com", _COOKIES_A, origins_a, repo=repo)
    save_storage_state(".example.com", _COOKIES_B, origins_b, repo=repo, account_id="acc-b")

    assert load_storage_origins(".example.com", repo=repo)[0]["localStorage"]["k"] == "a"
    assert (
        load_storage_origins(".example.com", repo=repo, account_id="acc-b")[0][
            "localStorage"
        ]["k"]
        == "b"
    )


def test_merge_set_cookies_targets_correct_account(repo):
    """HIGH 回归：Set-Cookie 续期带 account_id 时只更新命名账号，不污染默认账号。"""
    from backend.tools.credential_vault import merge_set_cookies

    save_credential(".example.com", _COOKIES_A, repo=repo)
    save_credential(".example.com", _COOKIES_B, repo=repo, account_id="acc-b")

    changed = merge_set_cookies(
        ".example.com",
        ["SID=fresh; Path=/; Domain=.example.com"],
        "https://www.example.com/",
        repo=repo,
        account_id="acc-b",
    )
    assert changed == ["SID"]
    # 命名账号续期为新值；默认账号保持原值（不串号）
    assert load_credential(".example.com", repo=repo, account_id="acc-b")[0]["value"] == "fresh"
    assert load_credential(".example.com", repo=repo)[0]["value"] == "acct-a"



# ── BrowserAccountService CRUD ─────────────────────────────────


def test_create_and_list_accounts():
    service = BrowserAccountService()
    a1 = service.create_account(label="工作号", domain=".example.com", color="green")
    a2 = service.create_account(label="审批号", domain=".example.com", is_default=True)

    accounts = service.list_accounts(".example.com")
    labels = [a.label for a in accounts]

    assert a1.id != a2.id
    assert "工作号" in labels
    assert "审批号" in labels
    # 默认账号排前
    assert accounts[0].label == "审批号"
    assert accounts[0].is_default is True


def test_create_account_duplicate_label_raises():
    service = BrowserAccountService()
    service.create_account(label="工作号", domain=".example.com")
    with pytest.raises(ValueError, match="已存在账号"):
        service.create_account(label="工作号", domain=".example.com")


def test_create_default_account_demotes_previous_default():
    service = BrowserAccountService()
    first = service.create_account(label="A", domain=".example.com", is_default=True)
    second = service.create_account(label="B", domain=".example.com", is_default=True)

    refreshed_first = service.get_account(first.id)
    assert refreshed_first is not None
    assert refreshed_first.is_default is False
    assert service.get_account(second.id).is_default is True
    assert service.get_default_account(".example.com").id == second.id


def test_update_and_delete_account():
    service = BrowserAccountService()
    account = service.create_account(label="工作号", domain=".example.com")
    updated = service.update_account(account.id, label="新名字", notes="备注")
    assert updated.label == "新名字"
    assert updated.notes == "备注"

    assert service.delete_account(account.id) is True
    assert service.get_account(account.id) is None
    assert service.delete_account(account.id) is False


def test_delete_account_removes_named_credentials(repo):
    service = BrowserAccountService()
    account = service.create_account(label="工作号", domain=".example.com")
    save_credential(".example.com", _COOKIES_B, repo=repo, account_id=account.id)
    assert load_credential(".example.com", repo=repo, account_id=account.id) is not None

    service.delete_account(account.id)
    assert load_credential(".example.com", repo=repo, account_id=account.id) is None


def test_resolve_vault_account_id():
    service = BrowserAccountService()
    default = service.create_account(label="默认", domain=".example.com", is_default=True)
    named = service.create_account(label="工作号", domain=".example.com")

    assert service.resolve_vault_account_id("") is None
    assert service.resolve_vault_account_id(default.id) is None
    assert service.resolve_vault_account_id(named.id) == named.id
    # 未知账号原样返回
    assert service.resolve_vault_account_id("unknown-id") == "unknown-id"


# ── 懒迁移 ────────────────────────────────────────────────────


def test_ensure_legacy_accounts_migrates_flat_entries(repo):
    service = BrowserAccountService()
    save_credential(".legacy.com", _COOKIES_A, repo=repo)

    created = service.ensure_legacy_accounts()
    assert created >= 1

    accounts = service.list_accounts(".legacy.com")
    assert len(accounts) == 1
    assert accounts[0].label == "默认账号"
    assert accounts[0].is_default is True

    # 幂等：再次执行不重复建
    assert service.ensure_legacy_accounts() == 0


def test_ensure_legacy_accounts_skips_named_entries(repo):
    service = BrowserAccountService()
    save_credential(".named.com", _COOKIES_B, repo=repo, account_id="acc-b")

    created = service.ensure_legacy_accounts(".named.com")
    assert created == 0
    assert service.list_accounts(".named.com") == []


def test_ensure_legacy_accounts_with_existing_named_account(repo):
    """已有命名账号 + 平铺凭据 → 仍补登记默认账号（不被命名账号挡住）。"""
    service = BrowserAccountService()
    service.create_account(label="工作号", domain=".named.com")
    save_credential(".named.com", _COOKIES_A, repo=repo)

    created = service.ensure_legacy_accounts(".named.com")
    assert created == 1
    accounts = service.list_accounts(".named.com")
    assert len(accounts) == 2
    default_accounts = [a for a in accounts if a.is_default]
    assert len(default_accounts) == 1

