"""``iteration_ceiling`` 纯函数单测（2026-11-05 M3 · W2）。

覆盖 auto / fixed 两种预算模式共用的「到达上限」路径：
``plan_ceiling`` 的四个动作（extend / final_step / ask_user / stop）、
延长步长钳制、提问载荷与答案解析。
"""

from __future__ import annotations

import pytest

from backend.core.legacy.iteration_budget import BudgetAudit, BudgetConfig
from backend.core.legacy.iteration_ceiling import (
    build_ceiling_question,
    next_extended_budget,
    parse_ceiling_answer,
    plan_ceiling,
)

pytestmark = pytest.mark.unit

CONFIG = BudgetConfig(
    hard_cap=100,
    extension_ratio=0.5,
    min_extension=10,
    max_extension=20,
    max_extensions=2,
)


def _audit(stuck: float = 0.0, progress: int = 5) -> BudgetAudit:
    return BudgetAudit(stuck_score=stuck, progress_signals=progress)


def _plan(**overrides):
    kwargs = {
        "current_budget": 20,
        "dynamic_active": True,
        "config": CONFIG,
        "audit": _audit(),
        "auto_extensions": 0,
        "final_step_granted": False,
        "force_extend": False,
        "ask_available": True,
    }
    kwargs.update(overrides)
    return plan_ceiling(**kwargs)


# ---------------------------------------------------------------------------
# next_extended_budget
# ---------------------------------------------------------------------------


def test_next_extended_budget_uses_ratio() -> None:
    """current=20、ratio=0.5 → 延长 10 步。"""
    assert next_extended_budget(20, CONFIG) == 30


def test_next_extended_budget_respects_min_extension() -> None:
    """小额预算按 min_extension 兜底，避免只延长 1 步。"""
    assert next_extended_budget(4, CONFIG) == 14


def test_next_extended_budget_clamps_to_hard_cap() -> None:
    """接近硬顶时封顶，不越过 hard_cap。"""
    assert next_extended_budget(95, CONFIG) == 100


def test_next_extended_budget_always_advances_below_hard_cap() -> None:
    """步长为 0 时也至少 +1，保证有界续跑不会原地打转。"""
    config = BudgetConfig(hard_cap=100, min_extension=0, max_extension=0)
    assert next_extended_budget(5, config) == 6


# ---------------------------------------------------------------------------
# 首次到达上限：先延长或先发判定轮
# ---------------------------------------------------------------------------


def test_first_hit_fixed_mode_grants_final_step() -> None:
    """固定模式不自动延长：先发判定轮，给模型收尾机会。"""
    plan = _plan(dynamic_active=False)
    assert plan.action == "final_step"
    assert plan.reason == "fixed_budget"
    assert plan.automatic is False
    assert plan.next_budget == 20


def test_first_hit_dynamic_healthy_extends_automatically() -> None:
    """自动模式 + 审计通过 → 直接延长。"""
    plan = _plan()
    assert plan.action == "extend"
    assert plan.reason == "progress"
    assert plan.automatic is True
    assert plan.next_budget == 30


def test_first_hit_dynamic_stuck_grants_final_step() -> None:
    """审计判卡住时不延长，但仍给一次收尾机会。"""
    plan = _plan(audit=_audit(stuck=0.8))
    assert plan.action == "final_step"
    assert plan.reason == "stuck"


def test_first_hit_dynamic_no_progress_grants_final_step() -> None:
    plan = _plan(audit=_audit(progress=0))
    assert plan.action == "final_step"
    assert plan.reason == "no_progress"


def test_first_hit_extension_limit_grants_final_step() -> None:
    """自动延长配额耗尽 → 判定轮（模型可能已完成）。"""
    plan = _plan(auto_extensions=CONFIG.max_extensions)
    assert plan.action == "final_step"
    assert plan.reason == "extension_limit"


def test_first_hit_at_hard_cap_grants_final_step_with_hard_cap_reason() -> None:
    plan = _plan(current_budget=100)
    assert plan.action == "final_step"
    assert plan.reason == "hard_cap"


# ---------------------------------------------------------------------------
# 判定轮之后：询问 / 停止
# ---------------------------------------------------------------------------


def test_after_final_step_fixed_mode_asks_user() -> None:
    """固定模式判定轮后仍未完成 → 询问用户是否续跑。"""
    plan = _plan(dynamic_active=False, final_step_granted=True)
    assert plan.action == "ask_user"
    assert plan.reason == "fixed_budget"
    assert plan.next_budget == 30


def test_after_final_step_without_gate_stops() -> None:
    """提问闸口不可用（子代理 / 无人值守）→ 直接停止，不挂起。"""
    plan = _plan(dynamic_active=False, final_step_granted=True, ask_available=False)
    assert plan.action == "stop"
    assert plan.reason == "fixed_budget"


def test_after_final_step_at_hard_cap_stops() -> None:
    """硬顶处无法再延长 → 停止，即使闸口可用也不问。"""
    plan = _plan(current_budget=100, final_step_granted=True)
    assert plan.action == "stop"
    assert plan.reason == "hard_cap"


def test_after_final_step_dynamic_stuck_still_asks_user() -> None:
    """自动模式下卡住 → 询问用户（用户仍可手动决定续跑）。"""
    plan = _plan(final_step_granted=True, audit=_audit(stuck=0.8))
    assert plan.action == "ask_user"
    assert plan.reason == "stuck"


# ---------------------------------------------------------------------------
# 用户选择「自动继续」后的有界续跑
# ---------------------------------------------------------------------------


def test_force_extend_healthy_extends_even_in_fixed_mode() -> None:
    """用户选了自动继续 → 固定模式也自动延长（直到硬顶）。"""
    plan = _plan(dynamic_active=False, force_extend=True)
    assert plan.action == "extend"
    assert plan.automatic is True
    assert plan.next_budget == 30


def test_force_extend_first_hit_stuck_grants_final_step() -> None:
    """自动继续不绕开审计：首次撞上限若有卡住信号，先判定轮再停。"""
    plan = _plan(force_extend=True, audit=_audit(stuck=0.9))
    assert plan.action == "final_step"
    assert plan.reason == "stuck"


def test_force_extend_stuck_stops_without_asking() -> None:
    """自动继续模式卡住 → 直接停止（用户已授权自动，不再打扰）。"""
    plan = _plan(
        final_step_granted=True, force_extend=True, audit=_audit(stuck=0.9)
    )
    assert plan.action == "stop"
    assert plan.reason == "stuck"


def test_force_extend_no_progress_stops() -> None:
    plan = _plan(
        final_step_granted=True, force_extend=True, audit=_audit(progress=0)
    )
    assert plan.action == "stop"
    assert plan.reason == "no_progress"


def test_force_extend_at_hard_cap_stops() -> None:
    plan = _plan(current_budget=100, final_step_granted=True, force_extend=True)
    assert plan.action == "stop"
    assert plan.reason == "hard_cap"


# ---------------------------------------------------------------------------
# 提问载荷与答案解析
# ---------------------------------------------------------------------------


def test_build_ceiling_question_shape() -> None:
    payload = build_ceiling_question(20, 30, "fixed_budget")
    assert payload["header"] == "迭代预算"
    assert "20" in payload["question"]
    assert "fixed_budget" in payload["question"]
    labels = [opt["label"] for opt in payload["options"]]
    assert len(labels) == 3
    assert "30" in payload["options"][0]["description"]


@pytest.mark.parametrize(
    ("answers", "expected"),
    [
        (["继续 Continue（再延长一次）"], "continue"),
        (["自动继续 Auto-continue"], "auto"),
        (["停止 Stop"], "stop"),
        (["AUTO-CONTINUE"], "auto"),
        (["Continue"], "continue"),
        (["something else"], "stop"),
        ([], "stop"),
    ],
)
def test_parse_ceiling_answer(answers, expected) -> None:
    assert parse_ceiling_answer(answers) == expected


def test_parse_ceiling_answer_auto_wins_over_continue() -> None:
    """「自动继续」同时含「继续」，必须先匹配自动。"""
    assert parse_ceiling_answer(["自动继续"]) == "auto"


def test_question_options_roundtrip_through_parser() -> None:
    """提问载荷的每个选项 label 都能被解析器识别回对应动作。"""
    payload = build_ceiling_question(20, 30, "progress")
    parsed = [parse_ceiling_answer([opt["label"]]) for opt in payload["options"]]
    assert parsed == ["continue", "auto", "stop"]
