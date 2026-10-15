"""``resolve_tool_call_budget`` 优先级链单元测试。

覆盖三条路径：
  1. env ``SAGE_MAX_TOOL_CALLS_PER_RUN``（最高优先级）
  2. UI 可调 ``OrchSettings.max_tool_calls_per_run``（持久化到 app_settings）
  3. fallback 参数（默认 25）

任何非法值（< 1 / 非整数）回落下一层，永不抛错。

Mock 策略：与 ``test_orch_settings.py`` 保持一致 —— patch
``backend.orchestration.orch_settings.SettingsRepository``，避免触碰真实 SQLite。
"""

from __future__ import annotations

import os
from typing import Iterator
from unittest.mock import patch

import pytest

from backend.orchestration.orch_settings import (
    _DEFAULT_FALLBACK_BUDGET,
    resolve_tool_call_budget,
)

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("_clean_env")]

_PATCH_TARGET = "backend.orchestration.orch_settings.SettingsRepository"


@pytest.fixture()
def _clean_env() -> Iterator[None]:
    """确保 env 不泄漏到其他测试。"""
    key = "SAGE_MAX_TOOL_CALLS_PER_RUN"
    saved = os.environ.pop(key, None)
    try:
        yield
    finally:
        if saved is not None:
            os.environ[key] = saved
        else:
            os.environ.pop(key, None)


# ---------- env 路径 ----------


def test_default_is_25():
    with patch(_PATCH_TARGET) as repo_cls:
        repo_cls.return_value.get_json.return_value = None
        assert resolve_tool_call_budget() == _DEFAULT_FALLBACK_BUDGET
    assert _DEFAULT_FALLBACK_BUDGET == 25


def test_env_overrides_default():
    os.environ["SAGE_MAX_TOOL_CALLS_PER_RUN"] = "100"
    with patch(_PATCH_TARGET) as repo_cls:
        repo_cls.return_value.get_json.return_value = None
        assert resolve_tool_call_budget() == 100


def test_env_invalid_falls_through():
    os.environ["SAGE_MAX_TOOL_CALLS_PER_RUN"] = "not-a-number"
    with patch(_PATCH_TARGET) as repo_cls:
        repo_cls.return_value.get_json.return_value = None
        assert resolve_tool_call_budget() == _DEFAULT_FALLBACK_BUDGET


def test_env_zero_falls_through():
    # 0 不视为"不限"而是回落（与 agent.py legacy 行为一致）
    os.environ["SAGE_MAX_TOOL_CALLS_PER_RUN"] = "0"
    with patch(_PATCH_TARGET) as repo_cls:
        repo_cls.return_value.get_json.return_value = None
        assert resolve_tool_call_budget() == _DEFAULT_FALLBACK_BUDGET


def test_env_negative_falls_through():
    os.environ["SAGE_MAX_TOOL_CALLS_PER_RUN"] = "-5"
    with patch(_PATCH_TARGET) as repo_cls:
        repo_cls.return_value.get_json.return_value = None
        assert resolve_tool_call_budget() == _DEFAULT_FALLBACK_BUDGET


# ---------- UI (OrchSettings) 路径 ----------


def test_orch_settings_ui_value_picked_up():
    with patch(_PATCH_TARGET) as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxToolCallsPerRun": 100}
        }
        assert resolve_tool_call_budget() == 100


def test_orch_settings_zero_falls_through_to_fallback():
    # OrchSettings 值为 0 → 回落 fallback 参数
    with patch(_PATCH_TARGET) as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxToolCallsPerRun": 0}
        }
        assert resolve_tool_call_budget() == _DEFAULT_FALLBACK_BUDGET
        assert resolve_tool_call_budget(fallback=50) == 50


def test_orch_settings_invalid_type_falls_through():
    # 类型守卫：字符串被跳过 → 回落默认
    with patch(_PATCH_TARGET) as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxToolCallsPerRun": "lots"}
        }
        assert resolve_tool_call_budget() == _DEFAULT_FALLBACK_BUDGET


# ---------- 优先级链 ----------


def test_env_beats_orch_settings():
    os.environ["SAGE_MAX_TOOL_CALLS_PER_RUN"] = "200"
    with patch(_PATCH_TARGET) as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxToolCallsPerRun": 100}
        }
        assert resolve_tool_call_budget() == 200


def test_orch_settings_beats_fallback():
    with patch(_PATCH_TARGET) as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxToolCallsPerRun": 100}
        }
        # fallback=50 被 UI 值 100 压过
        assert resolve_tool_call_budget(fallback=50) == 100


def test_corrupt_settings_file_returns_default():
    # load_orch_settings 内部已捕获异常并返回默认 OrchSettings（max_tool_calls_per_run=25）
    # 所以 resolve_tool_call_budget 拿到的是默认值 25，而不是 fallback 参数
    with patch(_PATCH_TARGET) as repo_cls:
        repo_cls.return_value.get_json.side_effect = RuntimeError("boom")
        # 永不抛错，返回默认 25（load_orch_settings 内部已吞异常并返回默认值）
        assert resolve_tool_call_budget() == _DEFAULT_FALLBACK_BUDGET
        # fallback 参数被忽略 —— 因为 load_orch_settings 返回了默认值 25（≥1）
        assert resolve_tool_call_budget(fallback=77) == _DEFAULT_FALLBACK_BUDGET
