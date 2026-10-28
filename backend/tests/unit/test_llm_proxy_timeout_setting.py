"""LLM 代理上游超时配置读取（app_settings.llmProxyTimeoutS）单元测试。

覆盖：
1. 无配置时默认 60s（保持历史行为）
2. app_settings 值生效
3. 环境变量 SAGE_LLM_PROXY_TIMEOUT_S 仅在设置缺失/非法时作为回退生效
4. 非法值（非数字、过小、过大、bool）回退默认
5. 读取设置抛异常时不冒泡，回退默认
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.api import llm_proxy_routes as routes

pytestmark = pytest.mark.unit


class _Repo:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def get_json(self, key: str) -> object:
        assert key == "app_settings"
        return self._payload


class _BrokenRepo:
    def get_json(self, key: str) -> object:
        raise OSError("db unavailable")


def _with_settings(payload: object):
    return patch(
        "backend.data.settings_repo.SettingsRepository",
        lambda: _Repo(payload),
    )


def test_default_timeout_is_60s(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAGE_LLM_PROXY_TIMEOUT_S", raising=False)
    with _with_settings({}):
        assert routes._proxy_timeout_seconds() == 60.0


def test_settings_value_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAGE_LLM_PROXY_TIMEOUT_S", raising=False)
    with _with_settings({"llmProxyTimeoutS": 300}):
        assert routes._proxy_timeout_seconds() == 300.0


def test_settings_take_priority_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAGE_LLM_PROXY_TIMEOUT_S", "120")
    with _with_settings({"llmProxyTimeoutS": 300}):
        assert routes._proxy_timeout_seconds() == 300.0


def test_env_used_when_settings_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAGE_LLM_PROXY_TIMEOUT_S", "120")
    with _with_settings({}):
        assert routes._proxy_timeout_seconds() == 120.0


def test_value_is_clamped_to_upper_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAGE_LLM_PROXY_TIMEOUT_S", raising=False)
    with _with_settings({"llmProxyTimeoutS": 99999}):
        assert routes._proxy_timeout_seconds() == 1800.0


@pytest.mark.parametrize("bad", [0, -1, 4.9, "abc", None, True])
def test_invalid_settings_fall_back_to_default(
    monkeypatch: pytest.MonkeyPatch, bad: object
) -> None:
    monkeypatch.delenv("SAGE_LLM_PROXY_TIMEOUT_S", raising=False)
    with _with_settings({"llmProxyTimeoutS": bad}):
        assert routes._proxy_timeout_seconds() == 60.0


def test_invalid_env_falls_back_to_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAGE_LLM_PROXY_TIMEOUT_S", "not-a-number")
    with _with_settings({"llmProxyTimeoutS": 300}):
        assert routes._proxy_timeout_seconds() == 300.0


def test_settings_read_failure_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAGE_LLM_PROXY_TIMEOUT_S", raising=False)
    with patch("backend.data.settings_repo.SettingsRepository", lambda: _BrokenRepo()):
        assert routes._proxy_timeout_seconds() == 60.0
