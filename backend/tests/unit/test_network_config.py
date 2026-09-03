"""network_config 加载器单元测试。

配置读取失败必须 fail-safe 到 ONLINE（即现状行为）—— 读不出配置不应该
把用户既有能力锁死。
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


def test_missing_key_returns_online_default():
    policy = load_network_policy(repo=_FakeRepo(None))
    assert policy.mode is NetworkMode.ONLINE
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


def test_malformed_json_falls_back_to_online():
    policy = load_network_policy(repo=_FakeRepo("{not json"))
    assert policy.mode is NetworkMode.ONLINE


def test_non_object_json_falls_back_to_online():
    policy = load_network_policy(repo=_FakeRepo('["a", "b"]'))
    assert policy.mode is NetworkMode.ONLINE


def test_unknown_mode_falls_back_to_online():
    policy = load_network_policy(repo=_FakeRepo('{"mode": "carrier-pigeon"}'))
    assert policy.mode is NetworkMode.ONLINE


def test_wrong_field_type_falls_back_to_online():
    policy = load_network_policy(repo=_FakeRepo('{"mode": "intranet", "allowed_hosts": 42}'))
    assert policy.mode is NetworkMode.ONLINE


def test_bare_string_host_field_falls_back_to_online():
    policy = load_network_policy(
        repo=_FakeRepo('{"mode": "intranet", "allowed_hosts": "a.internal"}')
    )
    assert policy.mode is NetworkMode.ONLINE


def test_overbroad_wildcard_in_stored_config_falls_back_to_online():
    """__post_init__ 的 ValueError 也要被兜住，不能让坏配置炸掉工具注册。"""
    policy = load_network_policy(
        repo=_FakeRepo('{"mode": "intranet", "allowed_hosts": ["*.net"]}')
    )
    assert policy.mode is NetworkMode.ONLINE


def test_repo_raising_falls_back_to_online():
    class _BrokenRepo:
        def get(self, key):
            raise RuntimeError("db gone")

    policy = load_network_policy(repo=_BrokenRepo())
    assert policy.mode is NetworkMode.ONLINE


def test_network_policy_key_is_in_settings_repo_whitelist():
    from backend.data.settings_repo import SettingsRepository

    assert SETTINGS_KEY_NETWORK_POLICY in SettingsRepository.KEYS
