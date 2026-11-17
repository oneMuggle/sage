"""browser_action_repo 单元测试（M4 审计账本）。"""

from __future__ import annotations

import pytest

from backend.data import browser_action_repo

pytestmark = pytest.mark.unit


def _entry(**overrides) -> dict:
    entry = {
        "session_id": "b1",
        "conversation_id": "c1",
        "ts": 1737000000000,
        "domain": "example.com",
        "tool": "browser_navigate",
        "action": "navigate",
        "target_ref": "e1",
        "target_desc": "Example",
        "result": "ok",
        "approval": "auto",
        "duration_ms": 12,
    }
    entry.update(overrides)
    return entry


def _boom(*_args, **_kwargs):
    raise RuntimeError("db down")


def test_record_and_list_recent_roundtrip() -> None:
    browser_action_repo.record(_entry())

    rows = browser_action_repo.list_recent()

    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] == "b1"
    assert row["conversation_id"] == "c1"
    assert row["domain"] == "example.com"
    assert row["tool"] == "browser_navigate"
    assert row["action"] == "navigate"
    assert row["target_ref"] == "e1"
    assert row["result"] == "ok"
    assert row["approval"] == "auto"
    assert row["duration_ms"] == 12


def test_list_recent_filters_by_session_and_orders_desc() -> None:
    browser_action_repo.record(_entry(session_id="b1", ts=1))
    browser_action_repo.record(_entry(session_id="b2", ts=3))
    browser_action_repo.record(_entry(session_id="b1", ts=2))

    b1_rows = browser_action_repo.list_recent("b1")

    assert [row["ts"] for row in b1_rows] == [2, 1]
    assert all(row["session_id"] == "b1" for row in b1_rows)
    assert len(browser_action_repo.list_recent(None)) == 3


def test_list_recent_limit_is_clamped() -> None:
    for index in range(5):
        browser_action_repo.record(_entry(ts=index))

    assert len(browser_action_repo.list_recent(None, 2)) == 2
    assert len(browser_action_repo.list_recent(None, 0)) == 1  # 下限 1
    assert len(browser_action_repo.list_recent(None, 9999)) == 5


def test_normalizes_invalid_enum_and_bounds() -> None:
    browser_action_repo.record(
        _entry(result="weird", approval="weird", target_desc="x" * 500, duration_ms=-5)
    )

    row = browser_action_repo.list_recent()[0]
    assert row["result"] == "error"
    assert row["approval"] == "auto"
    assert len(row["target_desc"]) == browser_action_repo.MAX_TARGET_DESC
    assert row["duration_ms"] == 0


def test_record_failure_is_swallowed(monkeypatch) -> None:
    monkeypatch.setattr(browser_action_repo, "get_database", _boom)

    browser_action_repo.record(_entry())  # 不抛异常


def test_list_recent_failure_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr(browser_action_repo, "get_database", _boom)

    assert browser_action_repo.list_recent() == []
