"""WakeStore 单元测试（A4 Suspend-Resume）。

覆盖 backend/application/services/wake_store.py：
- add_wake 持久化 + 重复 id 报错
- get_due_wakes 的到期判定（timer / completion / event 三分支）
- mark_fired / complete_job / fire_event 状态迁移
- 多实例共享同一 Database 的 schema 幂等性
- get_wake_store / reset_wake_store 单例语义
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.application.services import wake_store as wake_store_mod
from backend.application.services.wake_store import WakeStore, get_wake_store
from backend.domain.wake import Wake, WakeKind, WakeState, to_utc_iso

pytestmark = pytest.mark.unit


def _utc(**delta) -> str:
    """相对当前的 UTC ISO 时间戳（默认 now）。"""
    return to_utc_iso(datetime.now(timezone.utc) + timedelta(**delta))  # noqa: UP017


@pytest.fixture()
def store():
    """绑定 autouse 临时数据库的 WakeStore。"""
    return WakeStore()


# --------------------------------------------------------------------------- #
# add_wake / get_wake
# --------------------------------------------------------------------------- #


def test_add_wake_persists_all_fields(store):
    wake = Wake.create(
        "sess-1",
        WakeKind.TIMER,
        fire_at=_utc(seconds=30),
        note="轮询构建",
    )
    store.add_wake(wake)

    fetched = store.get_wake(wake.id)
    assert fetched is not None
    assert fetched.id == wake.id
    assert fetched.session_id == "sess-1"
    assert fetched.kind is WakeKind.TIMER
    assert fetched.state is WakeState.PENDING
    assert fetched.fire_at == wake.fire_at
    assert fetched.note == "轮询构建"
    assert fetched.fired_at is None


def test_add_wake_duplicate_id_raises_value_error(store):
    wake = Wake.create("sess-1", WakeKind.TIMER, fire_at=_utc(seconds=1))
    store.add_wake(wake)
    with pytest.raises(ValueError, match="already exists"):
        store.add_wake(wake)


def test_get_wake_unknown_returns_none(store):
    assert store.get_wake("nope") is None


# --------------------------------------------------------------------------- #
# get_due_wakes
# --------------------------------------------------------------------------- #


def test_future_timer_is_not_due(store):
    store.add_wake(Wake.create("s", WakeKind.TIMER, fire_at=_utc(seconds=3600)))
    assert store.get_due_wakes() == []


def test_past_timer_is_due(store):
    wake = store.add_wake(Wake.create("s", WakeKind.TIMER, fire_at=_utc(seconds=-1)))
    due = store.get_due_wakes()
    assert [w.id for w in due] == [wake.id]


def test_due_check_respects_explicit_now(store):
    fire_at = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)  # noqa: UP017
    store.add_wake(Wake.create("s", WakeKind.TIMER, fire_at=to_utc_iso(fire_at)))
    # now 早于 fire_at → 不到期；晚于 → 到期
    assert store.get_due_wakes(now=fire_at - timedelta(minutes=1)) == []
    assert len(store.get_due_wakes(now=fire_at + timedelta(minutes=1))) == 1


def test_naive_now_is_interpreted_as_utc(store):
    fire_at = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)  # noqa: UP017
    store.add_wake(Wake.create("s", WakeKind.TIMER, fire_at=to_utc_iso(fire_at)))
    naive_now = datetime(2026, 8, 1, 12, 0, 1)  # noqa: DTZ001 — 有意验证 naive 按 UTC 解释
    assert len(store.get_due_wakes(now=naive_now)) == 1


def test_completion_wake_not_due_until_job_completes(store):
    wake = store.add_wake(Wake.create("s", WakeKind.COMPLETION, job_id="job-9"))
    assert store.get_due_wakes() == []

    affected = store.complete_job("job-9")
    assert [w.id for w in affected] == [wake.id]

    due = store.get_due_wakes()
    assert [w.id for w in due] == [wake.id]
    assert due[0].state is WakeState.DUE


def test_complete_job_only_matches_pending_completion_wakes(store):
    # timer wake 带 job_id 不应被误标（kind 不匹配）
    store.add_wake(
        Wake.create("s", WakeKind.TIMER, fire_at=_utc(hours=1), job_id=None)
    )
    event_wake = store.add_wake(Wake.create("s", WakeKind.EVENT, event_key="job-9"))
    assert store.complete_job("job-9") == []
    # event wake 仍在 pending，不被 complete_job 影响
    assert store.get_wake(event_wake.id).state is WakeState.PENDING


def test_event_wake_not_due_until_event_fires(store):
    wake = store.add_wake(Wake.create("s", WakeKind.EVENT, event_key="deploy.done"))
    assert store.get_due_wakes() == []

    affected = store.fire_event("deploy.done")
    assert [w.id for w in affected] == [wake.id]
    assert [w.id for w in store.get_due_wakes()] == [wake.id]


def test_fired_wakes_are_never_due_again(store):
    wake = store.add_wake(Wake.create("s", WakeKind.TIMER, fire_at=_utc(seconds=-1)))
    assert store.mark_fired(wake.id) is True
    assert store.get_due_wakes() == []
    assert store.get_wake(wake.id).state is WakeState.FIRED
    assert store.get_wake(wake.id).fired_at is not None


def test_due_wakes_ordered_oldest_first(store):
    later = store.add_wake(Wake.create("s", WakeKind.TIMER, fire_at=_utc(seconds=-10)))
    earlier = store.add_wake(Wake.create("s", WakeKind.TIMER, fire_at=_utc(seconds=-100)))
    assert [w.id for w in store.get_due_wakes()] == [earlier.id, later.id]


def test_due_scan_limit_is_respected(store):
    for _ in range(5):
        store.add_wake(Wake.create("s", WakeKind.TIMER, fire_at=_utc(seconds=-1)))
    assert len(store.get_due_wakes(limit=3)) == 3


# --------------------------------------------------------------------------- #
# 状态迁移
# --------------------------------------------------------------------------- #


def test_mark_fired_is_idempotent(store):
    wake = store.add_wake(Wake.create("s", WakeKind.TIMER, fire_at=_utc(seconds=-1)))
    assert store.mark_fired(wake.id) is True
    assert store.mark_fired(wake.id) is False  # 已 fired
    assert store.mark_fired("unknown") is False  # 不存在


def test_complete_job_is_idempotent(store):
    store.add_wake(Wake.create("s", WakeKind.COMPLETION, job_id="j1"))
    assert len(store.complete_job("j1")) == 1
    assert store.complete_job("j1") == []  # 已是 due，不重复迁移


def test_pending_filters_by_session_and_state(store):
    w1 = store.add_wake(Wake.create("s1", WakeKind.TIMER, fire_at=_utc(hours=1)))
    w2 = store.add_wake(Wake.create("s2", WakeKind.TIMER, fire_at=_utc(hours=1)))
    w3 = store.add_wake(Wake.create("s1", WakeKind.TIMER, fire_at=_utc(seconds=-1)))
    store.mark_fired(w3.id)

    all_pending = store.pending()
    assert {w.id for w in all_pending} == {w1.id, w2.id}

    s1_pending = store.pending(session_id="s1")
    assert [w.id for w in s1_pending] == [w1.id]


# --------------------------------------------------------------------------- #
# schema 幂等 + 单例
# --------------------------------------------------------------------------- #


def test_second_store_instance_shares_data_and_schema(setup_test_db):
    """两个 WakeStore 实例共用同一 Database：ensure_schema 幂等。"""
    s1 = WakeStore(db=setup_test_db)
    wake = s1.add_wake(Wake.create("s", WakeKind.TIMER, fire_at=_utc(seconds=5)))
    s2 = WakeStore(db=setup_test_db)  # 再跑一次 CREATE TABLE IF NOT EXISTS
    assert s2.get_wake(wake.id) is not None


def test_singleton_and_reset(setup_test_db):
    a = get_wake_store()
    assert get_wake_store() is a
    wake_store_mod.reset_wake_store()
    b = get_wake_store()
    assert b is not a
