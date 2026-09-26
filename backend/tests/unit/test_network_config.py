"""network_config 加载器单元测试。

配置异常必须 fail-closed 到 OFFLINE；合法显式 ONLINE 保留。
"""

import pytest

from backend.domain.network_policy import NetworkMode
from backend.tools.network_config import (
    SETTINGS_KEY_NETWORK_POLICY,
    load_network_policy,
)

pytestmark = [pytest.mark.unit]


class _FakeRepo:
    """最小 SettingsRepository 替身：只实现 get()。"""

    def __init__(self, raw):
        self._raw = raw

    def get(self, key):
        assert key == SETTINGS_KEY_NETWORK_POLICY
        return self._raw


def test_missing_key_returns_offline_default():
    policy = load_network_policy(repo=_FakeRepo(None))
    assert policy.mode is NetworkMode.OFFLINE
    assert policy.allowed_hosts == ()


def test_valid_json_is_parsed():
    policy = load_network_policy(
        repo=_FakeRepo(
            '{"mode": "intranet", "allowed_hosts": ["*.example.internal"],'
            ' "insecure_tls_hosts": ["docs.example.internal"]}'
        )
    )
    assert policy.mode is NetworkMode.INTRANET
    assert policy.allowed_hosts == ("*.example.internal",)
    assert policy.insecure_tls_hosts == ("docs.example.internal",)


def test_malformed_json_falls_back_to_offline():
    policy = load_network_policy(repo=_FakeRepo("{not json"))
    assert policy.mode is NetworkMode.OFFLINE


def test_non_object_json_falls_back_to_offline():
    policy = load_network_policy(repo=_FakeRepo('["a", "b"]'))
    assert policy.mode is NetworkMode.OFFLINE


def test_unknown_mode_falls_back_to_offline():
    policy = load_network_policy(repo=_FakeRepo('{"mode": "carrier-pigeon"}'))
    assert policy.mode is NetworkMode.OFFLINE


def test_wrong_field_type_falls_back_to_offline():
    policy = load_network_policy(repo=_FakeRepo('{"mode": "intranet", "allowed_hosts": 42}'))
    assert policy.mode is NetworkMode.OFFLINE


def test_bare_string_host_field_falls_back_to_offline():
    policy = load_network_policy(
        repo=_FakeRepo('{"mode": "intranet", "allowed_hosts": "a.internal"}')
    )
    assert policy.mode is NetworkMode.OFFLINE


def test_overbroad_wildcard_in_stored_config_falls_back_to_offline():
    """__post_init__ 的 ValueError 也要被兜住，不能让坏配置炸掉工具注册。"""
    policy = load_network_policy(
        repo=_FakeRepo('{"mode": "intranet", "allowed_hosts": ["*.net"]}')
    )
    assert policy.mode is NetworkMode.OFFLINE


def test_repo_raising_falls_back_to_offline():
    class _BrokenRepo:
        def get(self, key):
            raise RuntimeError("db gone")

    policy = load_network_policy(repo=_BrokenRepo())
    assert policy.mode is NetworkMode.OFFLINE


def test_network_policy_key_is_in_settings_repo_whitelist():
    from backend.data.settings_repo import SettingsRepository

    assert SETTINGS_KEY_NETWORK_POLICY in SettingsRepository.KEYS


@pytest.mark.parametrize("raw", ["{}", '{"allowed_hosts": ["wiki.internal"]}'])
def test_missing_mode_denies_network(raw):
    assert load_network_policy(_FakeRepo(raw)).mode is NetworkMode.OFFLINE


def test_explicit_online_is_preserved():
    assert load_network_policy(_FakeRepo('{"mode":"online"}')).mode is NetworkMode.ONLINE


@pytest.mark.parametrize("mode", ["offline", "typo"])
def test_deployment_ceiling_cannot_be_weakened(monkeypatch, mode):
    monkeypatch.setenv("SAGE_DEPLOYMENT_MODE", mode)
    assert load_network_policy(_FakeRepo('{"mode":"online"}')).mode is NetworkMode.OFFLINE


def test_intranet_uses_admin_hosts_not_user_hosts(monkeypatch):
    monkeypatch.setenv("SAGE_DEPLOYMENT_MODE", "intranet")
    monkeypatch.setenv("SAGE_NETWORK_ALLOWED_HOSTS", "llm.corp.example, wiki.corp.example")
    policy = load_network_policy(_FakeRepo('{"mode":"online"}'))
    assert policy.check_host("https://llm.corp.example/") is None
    assert policy.check_host("https://public.example/") is not None
    assert not policy.insecure_tls_hosts


def test_invalid_admin_hosts_deny_network(monkeypatch):
    monkeypatch.setenv("SAGE_DEPLOYMENT_MODE", "intranet")
    monkeypatch.setenv("SAGE_NETWORK_ALLOWED_HOSTS", "*")
    assert load_network_policy(_FakeRepo(None)).mode is NetworkMode.OFFLINE
