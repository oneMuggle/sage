"""R159 — 工具调用熔断器（CircuitBreaker）单元测试。

覆盖：max_repeats 校验、前 N 次放行与熔断消息、不同参数独立计数、
mark_success 清零恢复、call_count 查询、reset、规范化键的键序无关性
与不可序列化兜底、不同工具隔离。
"""

from __future__ import annotations

import pytest

from backend.application.services.middleware.circuit_breaker import CircuitBreaker

pytestmark = pytest.mark.unit


def test_max_repeats_below_one_rejected():
    with pytest.raises(ValueError, match="max_repeats"):
        CircuitBreaker(max_repeats=0)


def test_calls_within_limit_pass():
    breaker = CircuitBreaker(max_repeats=3)
    for _ in range(3):
        assert breaker.check("t", {"a": 1}) is None


def test_call_over_limit_blocked_with_message():
    breaker = CircuitBreaker(max_repeats=2)
    breaker.check("t", {"a": 1})
    breaker.check("t", {"a": 1})
    block = breaker.check("t", {"a": 1})
    assert block is not None
    assert "CIRCUIT BREAKER" in block
    assert "'t'" in block
    assert "3 times" in block


def test_different_args_independent_counts():
    breaker = CircuitBreaker(max_repeats=1)
    assert breaker.check("t", {"a": 1}) is None
    assert breaker.check("t", {"a": 2}) is None  # 不同参数独立计数
    assert breaker.check("t", {"a": 1}) is not None  # 同参第二次熔断
    assert breaker.check("t", {"a": 2}) is not None


def test_different_tools_independent_counts():
    breaker = CircuitBreaker(max_repeats=1)
    assert breaker.check("t1", {"a": 1}) is None
    assert breaker.check("t2", {"a": 1}) is None


def test_mark_success_resets_count():
    breaker = CircuitBreaker(max_repeats=1)
    breaker.check("t", {"a": 1})
    breaker.mark_success("t", {"a": 1})
    assert breaker.check("t", {"a": 1}) is None  # 清零后重新放行


def test_call_count_reports():
    breaker = CircuitBreaker(max_repeats=3)
    assert breaker.call_count("t", {"a": 1}) == 0
    breaker.check("t", {"a": 1})
    breaker.check("t", {"a": 1})
    assert breaker.call_count("t", {"a": 1}) == 2


def test_reset_clears_all_counts():
    breaker = CircuitBreaker(max_repeats=1)
    breaker.check("t", {"a": 1})
    breaker.reset()
    assert breaker.call_count("t", {"a": 1}) == 0
    assert breaker.check("t", {"a": 1}) is None


def test_nested_dict_key_order_irrelevant():
    breaker = CircuitBreaker(max_repeats=1)
    breaker.check("t", {"outer": {"b": 1, "a": 2}})
    # 相同内容但内层键插入顺序不同 → 同键计数（第 2 次即熔断）
    assert breaker.check("t", {"outer": {"a": 2, "b": 1}}) is not None


def test_non_serializable_args_fall_back_to_repr():
    breaker = CircuitBreaker(max_repeats=1)
    obj = object()
    assert breaker.check("t", {"obj": obj}) is None  # default=str 兜底不抛错


def test_block_message_mentions_count_above_limit():
    breaker = CircuitBreaker(max_repeats=2)
    breaker.check("t", {"a": 1})
    breaker.check("t", {"a": 1})
    block = breaker.check("t", {"a": 1})
    assert "3 times" in block
