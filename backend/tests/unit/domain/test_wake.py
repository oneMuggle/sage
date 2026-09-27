"""R140 — Wake 唤醒领域模型单元测试。

覆盖：UTC ISO 归一化（naive/aware/后缀统一）、枚举值、create 工厂按
kind 校验必要字段、mark_due/mark_fired 状态机（不可变 replace、非法
迁移拒绝）、is_fired、frozen。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.domain.wake import Wake, WakeKind, WakeState, to_utc_iso

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 时间归一化
# ---------------------------------------------------------------------------


def test_to_utc_iso_naive_treated_as_utc():
    naive = datetime(2026, 9, 26, 12, 0, 0)  # noqa: DTZ001 — naive 正是被测语义
    assert to_utc_iso(naive) == "2026-09-26T12:00:00+00:00"


def test_to_utc_iso_aware_converts_timezone():
    tz = timezone(timedelta(hours=8))
    aware = datetime(2026, 9, 26, 20, 0, 0, tzinfo=tz)
    assert to_utc_iso(aware) == "2026-09-26T12:00:00+00:00"


def test_utc_now_iso_unified_suffix():
    from backend.domain.wake import utc_now_iso

    value = utc_now_iso()
    assert value.endswith("+00:00")  # 禁止 Z 后缀，字典序比较依赖统一格式


# ---------------------------------------------------------------------------
# create 工厂校验
# ---------------------------------------------------------------------------


def test_create_timer_without_fire_at_rejected():
    with pytest.raises(ValueError, match="fire_at"):
        Wake.create("s1", WakeKind.TIMER)


def test_create_completion_without_job_id_rejected():
    with pytest.raises(ValueError, match="job_id"):
        Wake.create("s1", WakeKind.COMPLETION)


def test_create_event_without_event_key_rejected():
    with pytest.raises(ValueError, match="event_key"):
        Wake.create("s1", WakeKind.EVENT)


def test_create_timer_happy_path():
    wake = Wake.create("s1", WakeKind.TIMER, fire_at="2026-10-01T00:00:00+00:00", note="n")
    assert len(wake.id) == 32  # uuid4 hex
    assert wake.session_id == "s1"
    assert wake.kind == WakeKind.TIMER
    assert wake.state == WakeState.PENDING
    assert wake.fire_at == "2026-10-01T00:00:00+00:00"
    assert wake.note == "n"
    assert wake.created_at  # 自动填充


def test_create_completion_and_event_happy_paths():
    completion = Wake.create("s", WakeKind.COMPLETION, job_id="job-1")
    event = Wake.create("s", WakeKind.EVENT, event_key="webhook.done")
    assert completion.job_id == "job-1"
    assert event.event_key == "webhook.done"


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------


def test_mark_due_from_pending_returns_new_instance():
    wake = Wake.create("s", WakeKind.TIMER, fire_at="t")
    due = wake.mark_due()
    assert due.state == WakeState.DUE
    assert wake.state == WakeState.PENDING  # 不可变：原实例不变
    assert due is not wake


def test_mark_due_from_non_pending_rejected():
    due = Wake.create("s", WakeKind.EVENT, event_key="k").mark_due()
    with pytest.raises(ValueError, match="cannot transition"):
        due.mark_due()


def test_mark_fired_from_pending_and_due():
    fired_at = "2026-10-01T01:00:00+00:00"
    pending = Wake.create("s", WakeKind.TIMER, fire_at="t")
    fired_from_pending = pending.mark_fired(fired_at)
    assert fired_from_pending.state == WakeState.FIRED
    assert fired_from_pending.fired_at == fired_at

    fired_from_due = pending.mark_due().mark_fired()
    assert fired_from_due.state == WakeState.FIRED
    assert fired_from_due.fired_at  # 缺省自动填充


def test_mark_fired_twice_rejected():
    wake = Wake.create("s", WakeKind.EVENT, event_key="k").mark_due().mark_fired()
    with pytest.raises(ValueError, match="already fired"):
        wake.mark_fired()


def test_is_fired_property():
    wake = Wake.create("s", WakeKind.EVENT, event_key="k")
    assert wake.is_fired is False
    assert wake.mark_fired().is_fired is True


def test_wake_frozen():
    import dataclasses

    wake = Wake.create("s", WakeKind.TIMER, fire_at="t")
    with pytest.raises(dataclasses.FrozenInstanceError):
        wake.state = WakeState.FIRED  # type: ignore[misc]


def test_enum_values():
    assert WakeKind.TIMER == "timer"
    assert WakeKind.COMPLETION == "completion"
    assert WakeKind.EVENT == "event"
    assert WakeState.PENDING == "pending"
    assert WakeState.DUE == "due"
    assert WakeState.FIRED == "fired"
