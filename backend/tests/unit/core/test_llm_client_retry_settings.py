# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""``llm_client._retry_settings()`` 行为测试。

2026-11-03 回归点（用户报告「设置页设了参数但分析说未设置」）：

- ``app_settings`` 里的 snake_case 键此前读不到（只认 camelCase）；
- 非法值此前静默丢弃，无任何日志，用户无从得知「设了没生效」；
- ``max_attempts`` 此前要求严格 ``isinstance(int)``，前端传来的 ``5.0`` 被丢。

本文件钉住修复后的行为：双形态键名都能读到、非法值落 warning 并回退默认。
"""

from __future__ import annotations

import logging

import pytest

from backend.core.legacy.llm_client import _retry_settings

pytestmark = pytest.mark.unit


def _patch_app_settings(monkeypatch, payload):
    """把 SettingsRepository.get_json 换成返回指定 app_settings。"""
    for env_key in (
        "SAGE_LLM_RETRY_MAX_ATTEMPTS",
        "SAGE_LLM_RETRY_BASE_DELAY_S",
        "SAGE_LLM_RETRY_MAX_DELAY_S",
        "SAGE_LLM_RETRY_TOTAL_BUDGET_S",
    ):
        monkeypatch.delenv(env_key, raising=False)

    def fake_get_json(self, key):
        return payload if key == "app_settings" else None

    monkeypatch.setattr(
        "backend.data.settings_repo.SettingsRepository.get_json", fake_get_json
    )


class TestAppSettingsRead:
    def test_camel_case_keys_are_applied(self, monkeypatch):
        _patch_app_settings(
            monkeypatch,
            {
                "llmRetryMaxAttempts": 8,
                "llmRetryBaseDelayS": 3.5,
                "llmRetryMaxDelayS": 90.0,
                "llmRetryTotalBudgetS": 420,
            },
        )
        assert _retry_settings() == (8, 3.5, 90.0, 420.0)

    def test_snake_case_keys_are_applied(self, monkeypatch):
        """snake_case 残留此前被静默忽略 —— 回归点。"""
        _patch_app_settings(
            monkeypatch,
            {
                "llm_retry_max_attempts": 7,
                "llm_retry_base_delay_s": 4.0,
                "llm_retry_max_delay_s": 120.0,
                "llm_retry_total_budget_s": 500,
            },
        )
        assert _retry_settings() == (7, 4.0, 120.0, 500.0)

    def test_float_valued_max_attempts_accepted(self, monkeypatch):
        """前端 NumberField 可能送出 5.0，此前被 isinstance(int) 判死 —— 回归点。"""
        _patch_app_settings(monkeypatch, {"llmRetryMaxAttempts": 5.0})
        max_attempts, _base, _max_delay, _budget = _retry_settings()
        assert max_attempts == 5
        assert isinstance(max_attempts, int)

    def test_partial_override_keeps_defaults(self, monkeypatch):
        _patch_app_settings(monkeypatch, {"llmRetryMaxAttempts": 9})
        max_attempts, base_delay, max_delay, budget = _retry_settings()
        assert max_attempts == 9
        assert base_delay == 2.0
        assert max_delay == 60.0
        assert budget == 300.0


class TestInvalidValueLogging:
    def test_invalid_max_attempts_logs_warning(self, monkeypatch, caplog):
        _patch_app_settings(monkeypatch, {"llmRetryMaxAttempts": 0})
        with caplog.at_level(logging.WARNING, logger="backend.core.retry_defaults"):
            max_attempts, _base, _max_delay, _budget = _retry_settings()
        assert max_attempts == 5
        assert "llmRetryMaxAttempts" in caplog.text
        # 警告须指明值来自哪一层，用户才能判断是「设错了」还是「没保存」
        assert "app_settings" in caplog.text

    def test_invalid_max_delay_logs_warning(self, monkeypatch, caplog):
        _patch_app_settings(monkeypatch, {"llmRetryMaxDelayS": 0.5})
        with caplog.at_level(logging.WARNING, logger="backend.core.retry_defaults"):
            _max_attempts, _base, max_delay, _budget = _retry_settings()
        assert max_delay == 60.0
        assert "llmRetryMaxDelayS" in caplog.text

    def test_invalid_env_logs_warning(self, monkeypatch, caplog):
        _patch_app_settings(monkeypatch, {})
        monkeypatch.setenv("SAGE_LLM_RETRY_MAX_ATTEMPTS", "abc")
        with caplog.at_level(logging.WARNING, logger="backend.core.retry_defaults"):
            max_attempts, _base, _max_delay, _budget = _retry_settings()
        assert max_attempts == 5
        assert "llmRetryMaxAttempts" in caplog.text
        assert "env" in caplog.text


class TestEnvPrecedence:
    def test_env_overrides_app_settings(self, monkeypatch):
        _patch_app_settings(monkeypatch, {"llmRetryMaxAttempts": 10})
        monkeypatch.setenv("SAGE_LLM_RETRY_MAX_ATTEMPTS", "20")
        max_attempts, _base, _max_delay, _budget = _retry_settings()
        assert max_attempts == 20

    def test_env_overrides_app_settings_delay(self, monkeypatch):
        _patch_app_settings(monkeypatch, {"llmRetryBaseDelayS": 3.0})
        monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "7")
        _max_attempts, base_delay, _max_delay, _budget = _retry_settings()
        assert base_delay == 7.0


class TestDefaults:
    def test_empty_app_settings_returns_new_defaults(self, monkeypatch):
        _patch_app_settings(monkeypatch, {})
        assert _retry_settings() == (5, 2.0, 60.0, 300.0)

    def test_missing_repo_returns_new_defaults(self, monkeypatch):
        """SettingsRepository 读失败不应抛错，回退默认。"""
        for env_key in (
            "SAGE_LLM_RETRY_MAX_ATTEMPTS",
            "SAGE_LLM_RETRY_BASE_DELAY_S",
            "SAGE_LLM_RETRY_MAX_DELAY_S",
            "SAGE_LLM_RETRY_TOTAL_BUDGET_S",
        ):
            monkeypatch.delenv(env_key, raising=False)

        def boom(self, key):
            raise OSError("db locked")

        monkeypatch.setattr(
            "backend.data.settings_repo.SettingsRepository.get_json", boom
        )
        assert _retry_settings() == (5, 2.0, 60.0, 300.0)
