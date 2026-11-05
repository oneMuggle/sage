"""Tests for backend.core.retry_defaults — LLM 重试配置单一真相源.

覆盖:
- 默认值（空输入）
- app_settings 覆盖（camelCase + snake_case）
- env 覆盖（优先级高于 app_settings）
- 来源标注（app_settings / env / default）
- 类型/范围校验 + warning 日志
- 交叉校验 base_delay <= max_delay
- RETRY_DEFAULTS 结构完整性
"""

from __future__ import annotations

import logging
import math
import os
from unittest.mock import patch

import pytest

from backend.core.retry_defaults import (
    RETRY_DEFAULTS,
    RETRY_KEYS,
    RetrySettings,
    RetrySettingsValueError,
    resolve_retry_settings,
    validate_retry_values,
)


@pytest.fixture(autouse=True)
def _clear_retry_env(monkeypatch):
    """默认值/覆盖测试必须不受环境里残留的 SAGE_LLM_RETRY_* 影响."""
    for name in (
        "SAGE_LLM_RETRY_MAX_ATTEMPTS",
        "SAGE_LLM_RETRY_BASE_DELAY_S",
        "SAGE_LLM_RETRY_MAX_DELAY_S",
        "SAGE_LLM_RETRY_TOTAL_BUDGET_S",
    ):
        monkeypatch.delenv(name, raising=False)

# ---------------------------------------------------------------------------
# 默认值
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_retry_defaults_has_four_keys(self):
        assert set(RETRY_DEFAULTS.keys()) == set(RETRY_KEYS)
        assert len(RETRY_DEFAULTS) == 4

    def test_retry_defaults_values(self):
        assert RETRY_DEFAULTS["llmRetryMaxAttempts"] == 5
        assert RETRY_DEFAULTS["llmRetryBaseDelayS"] == 2.0
        assert RETRY_DEFAULTS["llmRetryMaxDelayS"] == 60.0
        assert RETRY_DEFAULTS["llmRetryTotalBudgetS"] == 300

    def test_empty_input_returns_defaults(self):
        result = resolve_retry_settings(None)
        assert result.max_attempts == 5
        assert result.base_delay_s == 2.0
        assert result.max_delay_s == 60.0
        assert result.total_budget_s == 300.0
        assert all(v == "default" for v in result.sources.values())

    def test_empty_dict_returns_defaults(self):
        result = resolve_retry_settings({})
        assert result.max_attempts == 5
        assert all(v == "default" for v in result.sources.values())


# ---------------------------------------------------------------------------
# app_settings 覆盖
# ---------------------------------------------------------------------------


class TestAppSettingsOverride:
    def test_camel_case_keys_read(self):
        raw = {
            "llmRetryMaxAttempts": 10,
            "llmRetryBaseDelayS": 5.0,
            "llmRetryMaxDelayS": 120.0,
            "llmRetryTotalBudgetS": 600,
        }
        result = resolve_retry_settings(raw)
        assert result.max_attempts == 10
        assert result.base_delay_s == 5.0
        assert result.max_delay_s == 120.0
        assert result.total_budget_s == 600.0
        assert all(v == "app_settings" for v in result.sources.values())

    def test_snake_case_keys_normalized(self):
        """to_camel 归一化: snake_case 键也能被识别."""
        raw = {
            "llm_retry_max_attempts": 8,
            "llm_retry_base_delay_s": 3.0,
            "llm_retry_max_delay_s": 90.0,
            "llm_retry_total_budget_s": 450,
        }
        result = resolve_retry_settings(raw)
        assert result.max_attempts == 8
        assert result.base_delay_s == 3.0
        assert result.max_delay_s == 90.0
        assert result.total_budget_s == 450.0
        assert all(v == "app_settings" for v in result.sources.values())

    def test_partial_override(self):
        """只设一个键，其余走默认."""
        raw = {"llmRetryMaxAttempts": 7}
        result = resolve_retry_settings(raw)
        assert result.max_attempts == 7
        assert result.sources["llmRetryMaxAttempts"] == "app_settings"
        assert result.base_delay_s == 2.0
        assert result.sources["llmRetryBaseDelayS"] == "default"

    def test_float_valued_int_accepted(self):
        """max_attempts = 5.0 (float) 应被接受为 5."""
        raw = {"llmRetryMaxAttempts": 5.0}
        result = resolve_retry_settings(raw)
        assert result.max_attempts == 5
        assert isinstance(result.max_attempts, int)


# ---------------------------------------------------------------------------
# env 覆盖
# ---------------------------------------------------------------------------


class TestEnvOverride:
    def test_env_overrides_app_settings(self):
        """env 优先级高于 app_settings."""
        raw = {"llmRetryMaxAttempts": 10}
        env = {"SAGE_LLM_RETRY_MAX_ATTEMPTS": "20"}
        with patch.dict(os.environ, env, clear=False):
            result = resolve_retry_settings(raw)
        assert result.max_attempts == 20
        assert result.sources["llmRetryMaxAttempts"] == "env"

    def test_env_override_all_four(self):
        env = {
            "SAGE_LLM_RETRY_MAX_ATTEMPTS": "15",
            "SAGE_LLM_RETRY_BASE_DELAY_S": "4.0",
            "SAGE_LLM_RETRY_MAX_DELAY_S": "90.0",
            "SAGE_LLM_RETRY_TOTAL_BUDGET_S": "500",
        }
        with patch.dict(os.environ, env, clear=False):
            result = resolve_retry_settings(None)
        assert result.max_attempts == 15
        assert result.base_delay_s == 4.0
        assert result.max_delay_s == 90.0
        assert result.total_budget_s == 500.0
        assert all(v == "env" for v in result.sources.values())

    def test_env_empty_string_treated_as_unset(self):
        """空串 env 不应覆盖."""
        env = {"SAGE_LLM_RETRY_MAX_ATTEMPTS": ""}
        with patch.dict(os.environ, env, clear=False):
            result = resolve_retry_settings(None)
        assert result.max_attempts == 5
        assert result.sources["llmRetryMaxAttempts"] == "default"


# ---------------------------------------------------------------------------
# 类型/范围校验
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_max_attempts_string(self, caplog):
        raw = {"llmRetryMaxAttempts": "not_a_number"}
        with caplog.at_level(logging.WARNING, logger="backend.core.retry_defaults"):
            result = resolve_retry_settings(raw)
        assert result.max_attempts == 5  # fallback
        assert result.sources["llmRetryMaxAttempts"] == "default"
        assert "llmRetryMaxAttempts" in caplog.text

    def test_invalid_max_attempts_zero(self, caplog):
        """max_attempts = 0 不在 >= 1 范围内."""
        raw = {"llmRetryMaxAttempts": 0}
        with caplog.at_level(logging.WARNING, logger="backend.core.retry_defaults"):
            result = resolve_retry_settings(raw)
        assert result.max_attempts == 5
        assert result.sources["llmRetryMaxAttempts"] == "default"

    def test_invalid_max_attempts_negative(self, caplog):
        raw = {"llmRetryMaxAttempts": -1}
        with caplog.at_level(logging.WARNING, logger="backend.core.retry_defaults"):
            result = resolve_retry_settings(raw)
        assert result.max_attempts == 5

    def test_invalid_max_attempts_bool(self, caplog):
        """bool 不应被接受为 int."""
        raw = {"llmRetryMaxAttempts": True}
        with caplog.at_level(logging.WARNING, logger="backend.core.retry_defaults"):
            result = resolve_retry_settings(raw)
        assert result.max_attempts == 5

    def test_invalid_base_delay_negative(self, caplog):
        raw = {"llmRetryBaseDelayS": -1.0}
        with caplog.at_level(logging.WARNING, logger="backend.core.retry_defaults"):
            result = resolve_retry_settings(raw)
        assert result.base_delay_s == 2.0
        assert result.sources["llmRetryBaseDelayS"] == "default"

    def test_invalid_max_delay_below_one(self, caplog):
        raw = {"llmRetryMaxDelayS": 0.5}
        with caplog.at_level(logging.WARNING, logger="backend.core.retry_defaults"):
            result = resolve_retry_settings(raw)
        assert result.max_delay_s == 60.0
        assert result.sources["llmRetryMaxDelayS"] == "default"

    def test_invalid_total_budget_negative(self, caplog):
        raw = {"llmRetryTotalBudgetS": -10}
        with caplog.at_level(logging.WARNING, logger="backend.core.retry_defaults"):
            result = resolve_retry_settings(raw)
        assert result.total_budget_s == 300.0

    def test_zero_base_delay_is_valid(self):
        """base_delay = 0 是合法的（表示无退避）."""
        raw = {"llmRetryBaseDelayS": 0}
        result = resolve_retry_settings(raw)
        assert result.base_delay_s == 0.0
        assert result.sources["llmRetryBaseDelayS"] == "app_settings"

    def test_zero_total_budget_is_valid(self):
        """total_budget = 0 是合法的（表示不限）."""
        raw = {"llmRetryTotalBudgetS": 0}
        result = resolve_retry_settings(raw)
        assert result.total_budget_s == 0.0

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "nan", "inf"])
    def test_non_finite_values_fall_back_instead_of_crashing(self, bad, caplog):
        """NaN/inf 必须回退默认：NaN 与任意数比较恒为 False 会绕过范围检查."""
        raw = {"llmRetryMaxAttempts": bad, "llmRetryBaseDelayS": bad}
        with caplog.at_level(logging.WARNING, logger="backend.core.retry_defaults"):
            result = resolve_retry_settings(raw)
        assert result.max_attempts == 5
        assert result.base_delay_s == 2.0
        assert result.sources["llmRetryMaxAttempts"] == "default"
        assert result.sources["llmRetryBaseDelayS"] == "default"

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), "nan", "inf"])
    def test_validate_rejects_non_finite_with_field(self, bad):
        """写入侧应稳定抛 RetrySettingsValueError（而非 ValueError/OverflowError）."""
        with pytest.raises(RetrySettingsValueError) as excinfo:
            validate_retry_values({"llmRetryMaxAttempts": bad})
        assert excinfo.value.field == "llmRetryMaxAttempts"

    def test_resolved_floats_are_finite(self):
        """任何路径解析出的值都必须有限，绝不能让 NaN 流入 sleep()."""
        raw = {
            "llmRetryBaseDelayS": "nan",
            "llmRetryMaxDelayS": "inf",
            "llmRetryTotalBudgetS": "nan",
        }
        result = resolve_retry_settings(raw)
        assert math.isfinite(result.base_delay_s)
        assert math.isfinite(result.max_delay_s)
        assert math.isfinite(result.total_budget_s)

    def test_huge_integer_falls_back_without_overflow(self, caplog):
        """JSON 可解析出 10**400，float() 会 OverflowError —— 必须回退默认."""
        raw = {"llmRetryBaseDelayS": 10**400, "llmRetryMaxDelayS": 10**400}
        with caplog.at_level(logging.WARNING, logger="backend.core.retry_defaults"):
            result = resolve_retry_settings(raw)
        assert result.base_delay_s == 2.0
        assert result.max_delay_s == 60.0

    def test_validate_rejects_huge_integer_with_field(self):
        with pytest.raises(RetrySettingsValueError) as excinfo:
            validate_retry_values({"llmRetryMaxDelayS": 10**400})
        assert excinfo.value.field == "llmRetryMaxDelayS"

    def test_validate_cross_check_rejects_base_greater_than_max(self):
        """写入侧必须拦截 base > max（否则运行时回退让用户看到「已自定义」却不生效）."""
        with pytest.raises(RetrySettingsValueError) as excinfo:
            validate_retry_values(
                {"llmRetryBaseDelayS": 100.0, "llmRetryMaxDelayS": 50.0}
            )
        assert excinfo.value.field == "llmRetryBaseDelayS"

    def test_validate_cross_check_against_effective_values(self):
        """payload 只有 base 时, 交叉校验用 effective (存量) 的 max 比对."""
        effective = {"llmRetryMaxDelayS": 30.0}  # 存量 max 30, base 要改成 100 → 冲突
        with pytest.raises(RetrySettingsValueError) as excinfo:
            validate_retry_values({"llmRetryBaseDelayS": 100.0}, effective)
        assert excinfo.value.field == "llmRetryBaseDelayS"

    def test_validate_cross_check_skips_when_neither_key_in_payload(self):
        """改无关字段时, 存量 base>max 不得阻断提交."""
        effective = {"llmRetryBaseDelayS": 100.0, "llmRetryMaxDelayS": 30.0}
        # 仅改 llmRetryMaxAttempts, 不应触发交叉校验
        validate_retry_values({"llmRetryMaxAttempts": 7}, effective)

    def test_validate_cross_check_uses_defaults_when_no_effective(self):
        """payload 只有 base=100, 无 effective —— 用默认 max=60 → 冲突."""
        with pytest.raises(RetrySettingsValueError) as excinfo:
            validate_retry_values({"llmRetryBaseDelayS": 100.0})
        assert excinfo.value.field == "llmRetryBaseDelayS"

    def test_validate_cross_check_max_field_flagged(self):
        """当只有 max 在 payload 且比有效 base 小, field 指向 max."""
        effective = {"llmRetryBaseDelayS": 100.0}
        with pytest.raises(RetrySettingsValueError) as excinfo:
            validate_retry_values({"llmRetryMaxDelayS": 30.0}, effective)
        assert excinfo.value.field == "llmRetryMaxDelayS"

    def test_validate_cross_check_ignores_out_of_range_legacy_half(self):
        """存量另一半越界时运行时本就会回退默认, 写入侧不应据此误报.

        存量 max=0.5 (越界, 运行时会回退 60) + payload base=1 → 有效配对
        1 <= 60, 不得拒绝。
        """
        effective = {"llmRetryMaxDelayS": 0.5}
        validate_retry_values({"llmRetryBaseDelayS": 1.0}, effective)

    def test_validate_cross_check_still_flags_when_other_half_falls_back_to_default(self):
        """存量 max 越界 → 运行时回退默认 60; payload base=100 仍应被拒."""
        effective = {"llmRetryMaxDelayS": 99999.0}
        with pytest.raises(RetrySettingsValueError) as excinfo:
            validate_retry_values({"llmRetryBaseDelayS": 100.0}, effective)
        assert excinfo.value.field == "llmRetryBaseDelayS"


# ---------------------------------------------------------------------------
# 交叉校验
# ---------------------------------------------------------------------------


class TestCrossValidation:
    def test_base_exceeds_max_both_fallback(self, caplog):
        """base_delay > max_delay → 二者都回退默认."""
        raw = {
            "llmRetryBaseDelayS": 100.0,
            "llmRetryMaxDelayS": 50.0,
        }
        with caplog.at_level(logging.WARNING, logger="backend.core.retry_defaults"):
            result = resolve_retry_settings(raw)
        assert result.base_delay_s == 2.0
        assert result.max_delay_s == 60.0
        assert result.sources["llmRetryBaseDelayS"] == "default"
        assert result.sources["llmRetryMaxDelayS"] == "default"
        assert "llmRetryBaseDelayS" in caplog.text


# ---------------------------------------------------------------------------
# RetrySettings 不可变
# ---------------------------------------------------------------------------


class TestRetrySettingsFrozen:
    def test_frozen_dataclass(self):
        result = resolve_retry_settings(None)
        assert isinstance(result, RetrySettings)
        with pytest.raises(AttributeError):
            result.max_attempts = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 防御性兜底
# ---------------------------------------------------------------------------


class TestDefensive:
    def test_non_dict_input(self):
        """非 dict 输入应被视为空."""
        result = resolve_retry_settings("not a dict")  # type: ignore[arg-type]
        assert result.max_attempts == 5

    def test_non_mapping_input(self):
        result = resolve_retry_settings([1, 2, 3])  # type: ignore[arg-type]
        assert result.max_attempts == 5
