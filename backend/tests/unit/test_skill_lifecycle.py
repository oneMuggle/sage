"""Unit tests for skill lifecycle — classify_lifecycle 纯函数 + SkillLifecycleStore。

不用 freezegun：classify 用注入的 now_ms + 相对时间戳；store 用 autouse 临时 SQLite。
"""

from unittest.mock import Mock

from backend.skills.lifecycle import (
    DEFAULT_STALE_THRESHOLD_MS,
    LIFECYCLE_ACTIVE,
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_STALE,
    SkillLifecycleStore,
    classify_lifecycle,
    get_lifecycle_store,
    reset_lifecycle_store,
)

_DAY = 24 * 60 * 60 * 1000
_NOW = 100 * _DAY  # 任意固定"当前"基准


# ---------- classify_lifecycle（纯函数） ---------- #


def test_archived_takes_priority():
    """archived=True 优先于 active/stale（即使最近用过）。"""
    assert classify_lifecycle(_NOW, True, _NOW) == LIFECYCLE_ARCHIVED


def test_never_used_is_stale():
    """last_used_at=None（usage 表无行）→ stale。"""
    assert classify_lifecycle(None, False, _NOW) == LIFECYCLE_STALE


def test_recent_use_is_active():
    """阈值内用过 → active。"""
    assert classify_lifecycle(_NOW - 1 * _DAY, False, _NOW) == LIFECYCLE_ACTIVE


def test_old_use_is_stale():
    """超阈值 → stale。"""
    assert classify_lifecycle(_NOW - 60 * _DAY, False, _NOW) == LIFECYCLE_STALE


def test_boundary_at_threshold_is_active():
    """恰在阈值边界（距今 == 阈值）→ active（<= 语义）。"""
    assert classify_lifecycle(_NOW - DEFAULT_STALE_THRESHOLD_MS, False, _NOW) == LIFECYCLE_ACTIVE
    assert (
        classify_lifecycle(_NOW - DEFAULT_STALE_THRESHOLD_MS - 1, False, _NOW) == LIFECYCLE_STALE
    )


def test_custom_threshold():
    """自定义阈值生效（7 天）。"""
    seven_days = 7 * _DAY
    assert classify_lifecycle(_NOW - 3 * _DAY, False, _NOW, seven_days) == LIFECYCLE_ACTIVE
    assert classify_lifecycle(_NOW - 10 * _DAY, False, _NOW, seven_days) == LIFECYCLE_STALE


# ---------- SkillLifecycleStore（真实临时 SQLite，autouse setup_test_db） ---------- #


def test_set_archived_roundtrip():
    store = get_lifecycle_store()
    store.set_archived("search", True)
    assert store.is_archived("search")
    assert "search" in store.get_archived_names()


def test_unarchive_removes():
    store = get_lifecycle_store()
    store.set_archived("search", True)
    store.set_archived("search", False)
    assert not store.is_archived("search")
    assert "search" not in store.get_archived_names()


def test_persists_across_store_instances():
    """DB 是持久真相：新 store 实例（同库）仍读到归档态。"""
    get_lifecycle_store().set_archived("coder", True)
    reset_lifecycle_store()
    assert "coder" in get_lifecycle_store().get_archived_names()


def test_is_archived_unknown_name_false():
    assert not get_lifecycle_store().is_archived("never-archived")


def test_get_archived_names_best_effort_on_db_error():
    """DB 异常 → 返回空集，不外抛。"""
    bad = SkillLifecycleStore(db=Mock(get_connection=Mock(side_effect=RuntimeError("boom"))))
    assert bad.get_archived_names() == set()
    assert bad.is_archived("x") is False
