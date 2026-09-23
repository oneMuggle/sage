# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""上下文压力计量测试（DSH 对标 R4，TM1）。"""

from __future__ import annotations

import pytest

from backend.chat.token_meter import ContextPressure, measure_request_messages

pytestmark = pytest.mark.unit


def _msg(role, content):
    return {"role": role, "content": content}


def test_measure_basic_shape():
    messages = [
        _msg("system", "系统提示" * 10),
        _msg("user", "问题一" * 10),
        _msg("assistant", "回答一" * 10),
        _msg("user", "问题二"),
    ]
    cp = measure_request_messages(messages, effective_window=100000)
    assert isinstance(cp, ContextPressure)
    assert cp.total_tokens > 0
    assert cp.budget_tokens == 10000 - 16384 or cp.budget_tokens > 0
    assert set(cp.by_role) == {"system", "user", "assistant"}
    assert 0 < cp.pressure <= 1.0
    assert cp.estimator == "estimate_messages_tokens"


def test_by_role_sums_to_total():
    messages = [
        _msg("system", "abc"),
        _msg("user", "def"),
        _msg("assistant", "ghi"),
        _msg("tool", "jkl"),
    ]
    cp = measure_request_messages(messages, effective_window=50000)
    assert sum(cp.by_role.values()) == cp.total_tokens
    assert cp.by_role["tool"] > 0


def test_pressure_scales_with_content():
    short = measure_request_messages([_msg("user", "hi")], effective_window=100000)
    long = measure_request_messages(
        [_msg("user", "hi" * 5000)], effective_window=100000
    )
    assert long.pressure > short.pressure
    assert long.pressure <= 1.0


def test_pressure_caps_at_one():
    """内容远超 budget 时 pressure 封顶 1.0（fail-safe 语义）。"""
    cp = measure_request_messages(
        [_msg("user", "字" * 100000)], effective_window=30000
    )
    assert cp.pressure == 1.0


def test_zero_budget_fail_safe():
    """窗口极小导致 budget ≤ 0 时 pressure 恒 1.0（防御语义）。"""
    cp = measure_request_messages([_msg("user", "hi")], effective_window=100)
    assert cp.budget_tokens == 0
    assert cp.pressure == 1.0


def test_empty_messages():
    cp = measure_request_messages([], effective_window=50000)
    assert cp.total_tokens == 0
    assert cp.by_role == {}
    assert cp.pressure == 0.0


def test_to_dict_shape():
    cp = measure_request_messages([_msg("user", "hi")], effective_window=50000)
    d = cp.to_dict()
    assert set(d.keys()) == {
        "total_tokens",
        "budget_tokens",
        "pressure",
        "by_role",
        "estimator",
    }
    assert isinstance(d["pressure"], float)


def test_env_override_budget_respected(monkeypatch):
    """env SAGE_HISTORY_TOKEN_BUDGET 覆盖时 budget 随之变化（同源口径）。"""
    monkeypatch.setenv("SAGE_HISTORY_TOKEN_BUDGET", "12345")
    cp = measure_request_messages([_msg("user", "hi")], effective_window=None)
    assert cp.budget_tokens == 12345
