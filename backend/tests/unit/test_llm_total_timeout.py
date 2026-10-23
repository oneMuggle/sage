# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""整轮任务 wall-clock 上限读取函数单测。

覆盖 :mod:`backend.core.legacy.llm_total_timeout`：

- :func:`llm_total_timeout_s` — 优先级 app_settings > env > 默认 1800
- :func:`llm_total_timeout_or_none` — 0.0 → None；正值原样返回

边界：非法 env 回退默认、负值回退默认、app_settings 负值/错类型忽略、
SettingsRepository 抛错回退、``0`` = 不限。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.core.legacy.llm_total_timeout import (
    _LLM_TOTAL_TIMEOUT_DEFAULT_S,
    llm_total_timeout_or_none,
    llm_total_timeout_s,
)

pytestmark = pytest.mark.unit

_ENV = "SAGE_LLM_TOTAL_TIMEOUT_S"


def _patch_settings(payload: Any) -> Any:
    """把 ``backend.data.settings_repo.SettingsRepository`` 换成返回 payload 的替身。"""
    repo = MagicMock()
    repo.return_value.get_json.return_value = payload
    return patch("backend.data.settings_repo.SettingsRepository", repo)


def _patch_settings_raising(exc: Exception) -> Any:
    repo = MagicMock()
    repo.return_value.get_json.side_effect = exc
    return patch("backend.data.settings_repo.SettingsRepository", repo)


# --- 默认值 ---------------------------------------------------------------


def test_default_when_nothing_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    with _patch_settings(None):
        assert llm_total_timeout_s() == _LLM_TOTAL_TIMEOUT_DEFAULT_S


def test_default_is_1800() -> None:
    """默认 1800s = 2 × orch.subagentTaskTimeoutS 默认 900s（事故 2026-10-22 成因）。"""
    assert _LLM_TOTAL_TIMEOUT_DEFAULT_S == 1800.0


# --- 优先级 ---------------------------------------------------------------


def test_env_used_when_app_settings_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, "300")
    with _patch_settings(None):
        assert llm_total_timeout_s() == 300.0


def test_app_settings_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """app_settings > env —— 用户已确认的优先级，UI 设定值不被环境变量遮蔽。"""
    monkeypatch.setenv(_ENV, "300")
    with _patch_settings({"llmTotalTimeoutS": 7200}):
        assert llm_total_timeout_s() == 7200.0


def test_app_settings_zero_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """app_settings = 0（不限）同样压过 env。"""
    monkeypatch.setenv(_ENV, "300")
    with _patch_settings({"llmTotalTimeoutS": 0}):
        assert llm_total_timeout_s() == 0.0


def test_app_settings_float_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    with _patch_settings({"llmTotalTimeoutS": 1800.5}):
        assert llm_total_timeout_s() == 1800.5


# --- 非法值回退 -----------------------------------------------------------


def test_illegal_env_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(_ENV, "not-a-number")
    with _patch_settings(None), caplog.at_level("WARNING"):
        assert llm_total_timeout_s() == _LLM_TOTAL_TIMEOUT_DEFAULT_S
    assert any(_ENV in rec.getMessage() for rec in caplog.records)


def test_negative_env_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(_ENV, "-100")
    with _patch_settings(None), caplog.at_level("WARNING"):
        assert llm_total_timeout_s() == _LLM_TOTAL_TIMEOUT_DEFAULT_S
    assert any("负值" in rec.getMessage() for rec in caplog.records)


def test_negative_app_settings_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """app_settings 负值 → 忽略，回退 env/默认。"""
    monkeypatch.delenv(_ENV, raising=False)
    with _patch_settings({"llmTotalTimeoutS": -50}):
        assert llm_total_timeout_s() == _LLM_TOTAL_TIMEOUT_DEFAULT_S


def test_wrong_type_app_settings_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    with _patch_settings({"llmTotalTimeoutS": "not a number"}):
        assert llm_total_timeout_s() == _LLM_TOTAL_TIMEOUT_DEFAULT_S


def test_bool_app_settings_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """bool 是 int 子类，显式排除，避免 True 被当成 1 秒。"""
    monkeypatch.delenv(_ENV, raising=False)
    with _patch_settings({"llmTotalTimeoutS": True}):
        assert llm_total_timeout_s() == _LLM_TOTAL_TIMEOUT_DEFAULT_S


def test_non_dict_app_settings_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """app_settings 返回非 dict → 当空 dict 处理。"""
    monkeypatch.delenv(_ENV, raising=False)
    with _patch_settings("not a dict"):
        assert llm_total_timeout_s() == _LLM_TOTAL_TIMEOUT_DEFAULT_S


def test_settings_repo_error_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """SettingsRepository 抛错（DB 损坏 / 锁）→ env 兜底，不抛。"""
    monkeypatch.setenv(_ENV, "420")
    with _patch_settings_raising(OSError("db locked")):
        assert llm_total_timeout_s() == 420.0


# --- llm_total_timeout_or_none --------------------------------------------


def test_or_none_returns_none_for_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """0.0 → None（asyncio.wait_for(timeout=None) = 不限）。"""
    monkeypatch.delenv(_ENV, raising=False)
    with _patch_settings({"llmTotalTimeoutS": 0}):
        assert llm_total_timeout_or_none() is None


def test_or_none_returns_positive_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    with _patch_settings({"llmTotalTimeoutS": 1800}):
        assert llm_total_timeout_or_none() == 1800.0


def test_or_none_returns_default_when_nothing_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    with _patch_settings(None):
        assert llm_total_timeout_or_none() == _LLM_TOTAL_TIMEOUT_DEFAULT_S
