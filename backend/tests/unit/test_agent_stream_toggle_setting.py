"""agent._should_stream 读取 app_settings.streaming 的单元测试。

语义（优先级从高到低）：
1. env SAGE_LLM_STREAMING ∈ {0,false,off,no} → 禁用（调试/测试用）
2. app_settings.streaming === false → 禁用
3. llm_client.stream_unsupported === True → 禁用（失败后自动回退）
4. 其余 → 启用

背景：2026-10-28 之前 settings.streaming 是「死设置」，没有任何代码消费，
用户关闭「流式输出」后上游仍收到 stream: true。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.core.legacy.agent import SageAgent

pytestmark = pytest.mark.unit


class _Repo:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def get_json(self, key: str) -> object:
        assert key == "app_settings"
        return self._payload


def _with_settings(payload: object):
    return patch(
        "backend.data.settings_repo.SettingsRepository",
        lambda: _Repo(payload),
    )


def _client(stream_unsupported: bool = False) -> MagicMock:
    client = MagicMock()
    client.stream_unsupported = stream_unsupported
    return client


def test_setting_false_disables_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAGE_LLM_STREAMING", raising=False)
    with _with_settings({"streaming": False}):
        assert SageAgent._should_stream(_client()) is False


def test_setting_true_enables_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAGE_LLM_STREAMING", raising=False)
    with _with_settings({"streaming": True}):
        assert SageAgent._should_stream(_client()) is True


def test_setting_absent_defaults_to_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAGE_LLM_STREAMING", raising=False)
    with _with_settings({}):
        assert SageAgent._should_stream(_client()) is True


def test_env_kill_switch_wins_over_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAGE_LLM_STREAMING", "0")
    with _with_settings({"streaming": True}):
        assert SageAgent._should_stream(_client()) is False


def test_stream_unsupported_still_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAGE_LLM_STREAMING", raising=False)
    with _with_settings({"streaming": True}):
        assert SageAgent._should_stream(_client(stream_unsupported=True)) is False


def test_settings_read_failure_defaults_to_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SAGE_LLM_STREAMING", raising=False)

    class _BrokenRepo:
        def get_json(self, key: str) -> object:
            raise OSError("db unavailable")

    with patch("backend.data.settings_repo.SettingsRepository", lambda: _BrokenRepo()):
        assert SageAgent._should_stream(_client()) is True
