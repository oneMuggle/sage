"""R132 — Agent ReAct 状态机单元测试。

覆盖：六态枚举、initial()、迁移表逐边合法断言、非法迁移与终态封闭、
AgentDecision 冻结值对象契约。
"""

from __future__ import annotations

import dataclasses

import pytest

from backend.domain.agent import AgentDecision, AgentState

pytestmark = pytest.mark.unit


def test_six_states_exist():
    assert [s.value for s in AgentState] == [
        "idle",
        "thinking",
        "acting",
        "observing",
        "done",
        "failed",
    ]


def test_initial_is_idle():
    assert AgentState.initial() == AgentState.IDLE


# ---------------------------------------------------------------------------
# 合法迁移
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (AgentState.IDLE, AgentState.THINKING),
        (AgentState.THINKING, AgentState.ACTING),
        (AgentState.THINKING, AgentState.DONE),
        (AgentState.THINKING, AgentState.FAILED),
        (AgentState.ACTING, AgentState.OBSERVING),
        (AgentState.ACTING, AgentState.FAILED),
        (AgentState.OBSERVING, AgentState.THINKING),
        (AgentState.OBSERVING, AgentState.DONE),
        (AgentState.OBSERVING, AgentState.FAILED),
    ],
)
def test_legal_transitions(frm, to):
    assert frm.can_transition_to(to) is True


# ---------------------------------------------------------------------------
# 非法迁移与终态
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (AgentState.IDLE, AgentState.ACTING),
        (AgentState.IDLE, AgentState.OBSERVING),
        (AgentState.IDLE, AgentState.DONE),
        (AgentState.IDLE, AgentState.FAILED),
        (AgentState.ACTING, AgentState.THINKING),
        (AgentState.THINKING, AgentState.OBSERVING),
        (AgentState.THINKING, AgentState.IDLE),
        (AgentState.DONE, AgentState.THINKING),
        (AgentState.FAILED, AgentState.IDLE),
    ],
)
def test_illegal_transitions(frm, to):
    assert frm.can_transition_to(to) is False


@pytest.mark.parametrize("terminal", [AgentState.DONE, AgentState.FAILED])
def test_terminal_states_are_closed(terminal):
    for other in AgentState:
        assert terminal.can_transition_to(other) is False


# ---------------------------------------------------------------------------
# AgentDecision 值对象
# ---------------------------------------------------------------------------


def test_decision_frozen_value_object():
    decision = AgentDecision(state=AgentState.ACTING, action_name="search", action_args={})
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.state = AgentState.DONE  # type: ignore[misc]


def test_decision_fields_default_none():
    decision = AgentDecision(state=AgentState.DONE, final_message="完成")
    assert decision.action_name is None
    assert decision.action_args is None
    assert decision.final_message == "完成"
