"""2026-10-28 — update_sage_config 对 ask_user_question 限制键的支持。

agent 自我配置工具必须能改这 5 个键（否则用户在设置页改了，
agent 用 update_sage_config 回写会报「越权字段」），且必须拦住
「最少选项数 > 最多选项数」这种自相矛盾的组合。
"""

from __future__ import annotations

import pytest

from backend.tools.config_tool import (
    _ALLOWED_ORCH_FIELDS,
    _ORCH_INTEGER_RANGES,
    _prepare_settings_update,
    _validate_ask_user_cross_fields,
    _validate_orch_updates,
)

pytestmark = pytest.mark.unit

_ASK_USER_FIELDS = (
    "maxConsecutiveUnansweredQuestions",
    "minOptionsPerQuestion",
    "maxOptionsPerQuestion",
    "maxClarifyQuestionsInPrompt",
    "maxClarifyQuestionsPerRound",
)


def test_config_tool_allows_ask_user_fields():
    """update_sage_config 允许改这 5 个 orch 键。"""
    for key in _ASK_USER_FIELDS:
        assert key in _ALLOWED_ORCH_FIELDS


@pytest.mark.parametrize("key", _ASK_USER_FIELDS)
def test_config_tool_defines_integer_range_for_ask_user_fields(key):
    """每个键都有整数区间约束（否则非 int 值可写入 orch 段）。"""
    assert key in _ORCH_INTEGER_RANGES


def test_config_tool_rejects_non_integer_ask_user_value():
    """非整数 → 拒绝。"""
    err = _validate_orch_updates({"maxConsecutiveUnansweredQuestions": "3"})
    assert err is not None
    assert "maxConsecutiveUnansweredQuestions" in err


def test_config_tool_rejects_out_of_range_ask_user_value():
    """越界 → 拒绝（0 对这些限制无意义）。"""
    err = _validate_orch_updates({"maxConsecutiveUnansweredQuestions": 0})
    assert err is not None
    assert "maxConsecutiveUnansweredQuestions" in err


def test_config_tool_rejects_min_greater_than_max():
    """min > max → 拒绝。"""
    err = _validate_ask_user_cross_fields(
        {"minOptionsPerQuestion": 5, "maxOptionsPerQuestion": 3}
    )
    assert err is not None
    assert "minOptionsPerQuestion" in err


def test_config_tool_accepts_min_less_equal_max():
    """min ≤ max → 通过。"""
    assert (
        _validate_ask_user_cross_fields(
            {"minOptionsPerQuestion": 2, "maxOptionsPerQuestion": 4}
        )
        is None
    )
    assert (
        _validate_ask_user_cross_fields(
            {"minOptionsPerQuestion": 3, "maxOptionsPerQuestion": 3}
        )
        is None
    )


def test_config_tool_cross_field_check_uses_merged_values():
    """只改一个键时，已持久化的另一个键同样参与比较。

    合并后比较而非仅看提交值 —— 否则用户把 min 调到 5 而库里 max 仍是 3，
    校验会漏过，落库成自相矛盾的组合。
    """
    current = {"orch": {"minOptionsPerQuestion": 5, "maxOptionsPerQuestion": 3}}
    candidate, err = _prepare_settings_update(
        current, {"maxOptionsPerQuestion": 4}, target="orch"
    )
    assert candidate is None
    assert err is not None
    assert "minOptionsPerQuestion" in err


def test_config_tool_cross_field_check_allows_consistent_partial_update():
    """只改一个键且合并后自洽 → 通过。"""
    current = {"orch": {"minOptionsPerQuestion": 2, "maxOptionsPerQuestion": 4}}
    candidate, err = _prepare_settings_update(
        current, {"minOptionsPerQuestion": 3}, target="orch"
    )
    assert err is None
    assert candidate is not None
    assert candidate["orch"]["minOptionsPerQuestion"] == 3
    assert candidate["orch"]["maxOptionsPerQuestion"] == 4


def test_config_tool_cross_field_check_defaults_non_int():
    """非 int 值回落 OrchSettings 默认值（min=2 / max=4），再参与比较。

    2026-10-28 review (MEDIUM-2): 旧逻辑 ``.get()`` 返回 None 直接跳过比较，
    agent 第一次只提交 ``min=5`` 时缺 ``max`` → 校验绕过 → 落库后与默认
    ``max=4`` 自相矛盾。新逻辑缺键回落数据类默认值再比较。
    """
    # min="3"(非 int → 默认 2), max=2 → 2 ≤ 2，通过
    assert (
        _validate_ask_user_cross_fields(
            {"minOptionsPerQuestion": "3", "maxOptionsPerQuestion": 2}
        )
        is None
    )
    # min 缺键 → 默认 2; max=1 → 2 > 1，拒绝
    err = _validate_ask_user_cross_fields({"maxOptionsPerQuestion": 1})
    assert err is not None
    assert "minOptionsPerQuestion" in err
    # max 缺键 → 默认 4; min=5 → 5 > 4，拒绝（旧逻辑此 case 会绕过）
    err = _validate_ask_user_cross_fields({"minOptionsPerQuestion": 5})
    assert err is not None
    assert "maxOptionsPerQuestion" in err
