"""
闲时延迟执行系统 — 单元测试

覆盖:
- execution_conditions.py: ExecutionCondition 序列化/反序列化
- idle_detector.py: IdleDetector 空闲等级判断
- condition_evaluator.py: 条件评估引擎
- autonomous_goals.py: Goal 模型 trigger_mode + execution_conditions 字段
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from backend.domain.execution_conditions import (
    ConditionType,
    ExecutionCondition,
    IdleLevel,
    TriggerMode,
    idle_condition,
    manual_condition,
    no_active_tasks_condition,
    resource_condition,
    time_window_condition,
)
from backend.services.idle_detector import IdleDetector
from backend.services.condition_evaluator import ConditionEvaluator


# ─── execution_conditions.py ─────────────────────────────────────────


class TestExecutionCondition:
    """ExecutionCondition 序列化测试"""

    def test_idle_condition_round_trip(self):
        cond = idle_condition(15)
        d = cond.to_dict()
        assert d["type"] == "idle"
        assert d["params"]["min_idle_minutes"] == 15

        restored = ExecutionCondition.from_dict(d)
        assert restored.type == ConditionType.IDLE
        assert restored.params["min_idle_minutes"] == 15

    def test_time_window_condition(self):
        cond = time_window_condition("02:00", "06:00")
        d = cond.to_dict()
        assert d["type"] == "time_window"
        assert d["params"]["start"] == "02:00"
        assert d["params"]["end"] == "06:00"

    def test_resource_condition(self):
        cond = resource_condition(max_cpu_pct=20, max_memory_pct=40)
        d = cond.to_dict()
        assert d["params"]["max_cpu_pct"] == 20
        assert d["params"]["max_memory_pct"] == 40

    def test_manual_condition(self):
        cond = manual_condition()
        assert cond.type == ConditionType.MANUAL
        assert cond.params == {}

    def test_no_active_tasks_condition(self):
        cond = no_active_tasks_condition()
        assert cond.type == ConditionType.NO_ACTIVE_TASKS

    def test_from_dict_missing_params(self):
        """向后兼容：缺少 params 字段时默认空字典"""
        cond = ExecutionCondition.from_dict({"type": "idle"})
        assert cond.params == {}


class TestTriggerMode:
    """TriggerMode 枚举测试"""

    def test_values(self):
        assert TriggerMode.IMMEDIATE.value == "immediate"
        assert TriggerMode.CONDITIONAL.value == "conditional"

    def test_from_string(self):
        assert TriggerMode("immediate") == TriggerMode.IMMEDIATE
        assert TriggerMode("conditional") == TriggerMode.CONDITIONAL


# ─── idle_detector.py ────────────────────────────────────────────────


class TestIdleDetector:
    """IdleDetector 空闲检测测试"""

    def test_initial_state_is_not_idle(self):
        """刚创建时视为刚活跃"""
        d = IdleDetector()
        assert d.get_idle_level() == IdleLevel.NONE
        assert d.get_idle_minutes() < 1

    def test_report_activity_resets_timer(self):
        d = IdleDetector()
        # 手动设置 last_activity 到很久之前（> 1800 秒 = DEEP）
        d._last_activity_ts = time.monotonic() - 3600
        assert d.get_idle_level() == IdleLevel.DEEP

        d.report_activity()
        assert d.get_idle_level() == IdleLevel.NONE
        assert d.get_idle_minutes() < 1

    def test_short_idle_level(self):
        d = IdleDetector(short_idle_seconds=5, deep_idle_seconds=30)
        d._last_activity_ts = time.monotonic() - 10  # 10 秒前
        assert d.get_idle_level() == IdleLevel.SHORT

    def test_deep_idle_level(self):
        d = IdleDetector(short_idle_seconds=5, deep_idle_seconds=30)
        d._last_activity_ts = time.monotonic() - 60  # 60 秒前
        assert d.get_idle_level() == IdleLevel.DEEP

    def test_is_idle_at_least(self):
        d = IdleDetector(short_idle_seconds=5, deep_idle_seconds=30)
        d._last_activity_ts = time.monotonic() - 60

        assert d.is_idle_at_least(IdleLevel.NONE)
        assert d.is_idle_at_least(IdleLevel.SHORT)
        assert d.is_idle_at_least(IdleLevel.DEEP)

    def test_is_idle_at_least_false(self):
        d = IdleDetector()
        d.report_activity()
        assert d.is_idle_at_least(IdleLevel.NONE)
        assert not d.is_idle_at_least(IdleLevel.SHORT)
        assert not d.is_idle_at_least(IdleLevel.DEEP)

    def test_get_status(self):
        d = IdleDetector()
        d.report_activity()
        status = d.get_status()
        assert status["idle_level"] == "none"
        assert "idle_seconds" in status
        assert "idle_minutes" in status
        assert "last_activity_epoch" in status
        assert status["short_idle_threshold"] == 300
        assert status["deep_idle_threshold"] == 1800

    def test_report_activity_with_epoch(self):
        d = IdleDetector()
        epoch = time.time()
        d.report_activity(epoch_ts=epoch)
        assert d.get_last_activity_epoch() == epoch


# ─── condition_evaluator.py ──────────────────────────────────────────


class TestConditionEvaluator:
    """条件评估引擎测试"""

    def _make_evaluator(self, idle_seconds: float = 0) -> ConditionEvaluator:
        detector = IdleDetector()
        if idle_seconds > 0:
            detector._last_activity_ts = time.monotonic() - idle_seconds
        twm = MagicMock()
        return ConditionEvaluator(idle_detector=detector, time_window_manager=twm)

    def test_empty_conditions_satisfied(self):
        ce = self._make_evaluator()
        assert ce.evaluate_all([]) is True

    def test_idle_condition_satisfied(self):
        ce = self._make_evaluator(idle_seconds=1200)  # 20 分钟
        cond = idle_condition(15)  # 需要 15 分钟
        assert ce.evaluate(cond) is True

    def test_idle_condition_not_satisfied(self):
        ce = self._make_evaluator(idle_seconds=60)  # 1 分钟
        cond = idle_condition(15)  # 需要 15 分钟
        assert ce.evaluate(cond) is False

    def test_manual_condition_never_satisfied(self):
        ce = self._make_evaluator()
        assert ce.evaluate(manual_condition()) is False

    def test_no_active_tasks_without_goal_service(self):
        """未注入 goal_service 时乐观返回 True"""
        ce = self._make_evaluator()
        assert ce.evaluate(no_active_tasks_condition()) is True

    def test_resource_condition_optimistic(self):
        """当前无 psutil，乐观返回 True"""
        ce = self._make_evaluator()
        assert ce.evaluate(resource_condition()) is True

    def test_and_semantics_all_pass(self):
        ce = self._make_evaluator(idle_seconds=1200)
        conditions = [idle_condition(15), no_active_tasks_condition()]
        assert ce.evaluate_all(conditions) is True

    def test_and_semantics_one_fails(self):
        ce = self._make_evaluator(idle_seconds=60)
        conditions = [idle_condition(15), no_active_tasks_condition()]
        assert ce.evaluate_all(conditions) is False

    def test_evaluate_with_details(self):
        ce = self._make_evaluator(idle_seconds=1200)
        conditions = [idle_condition(15), manual_condition()]
        result = ce.evaluate_with_details(conditions)
        assert result["all_satisfied"] is False
        assert len(result["conditions"]) == 2
        assert result["conditions"][0]["satisfied"] is True
        assert result["conditions"][1]["satisfied"] is False
        assert "detail" in result["conditions"][0]

    def test_time_window_condition_delegates(self):
        ce = self._make_evaluator()
        ce._time_window_manager.is_off_peak = MagicMock(return_value=True)
        cond = time_window_condition("22:00", "06:00")
        assert ce.evaluate(cond) is True
        ce._time_window_manager.is_off_peak.assert_called_once()


# ─── Goal model with new fields ──────────────────────────────────────


class TestGoalTriggerModeFields:
    """Goal 模型 trigger_mode + execution_conditions 字段测试"""

    def test_default_values(self):
        from backend.domain.autonomous_goals import Goal

        g = Goal(id="g1", name="test", description="desc")
        assert g.trigger_mode == TriggerMode.IMMEDIATE
        assert g.execution_conditions == []

    def test_conditional_with_conditions(self):
        from backend.domain.autonomous_goals import Goal

        conditions = [idle_condition(15), no_active_tasks_condition()]
        g = Goal(
            id="g2",
            name="deferred",
            description="desc",
            trigger_mode=TriggerMode.CONDITIONAL,
            execution_conditions=conditions,
        )
        assert g.trigger_mode == TriggerMode.CONDITIONAL
        assert len(g.execution_conditions) == 2

    def test_serialization_round_trip(self):
        from backend.domain.autonomous_goals import Goal

        conditions = [idle_condition(15)]
        g = Goal(
            id="g3",
            name="test",
            description="desc",
            trigger_mode=TriggerMode.CONDITIONAL,
            execution_conditions=conditions,
        )
        d = g.to_dict()
        assert d["trigger_mode"] == "conditional"
        assert len(d["execution_conditions"]) == 1

        g2 = Goal.from_dict(d)
        assert g2.trigger_mode == TriggerMode.CONDITIONAL
        assert g2.execution_conditions[0].type == ConditionType.IDLE

    def test_backward_compat_no_new_fields(self):
        """旧数据没有 trigger_mode / execution_conditions 时应使用默认值"""
        from backend.domain.autonomous_goals import Goal

        old_data = {
            "id": "old1",
            "name": "old goal",
            "description": "old",
            "status": "pending",
            "created_at": "2026-10-28T00:00:00",
        }
        g = Goal.from_dict(old_data)
        assert g.trigger_mode == TriggerMode.IMMEDIATE
        assert g.execution_conditions == []
