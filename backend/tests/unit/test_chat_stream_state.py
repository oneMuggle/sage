# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""chat_stream_state 单测（C2c，DSH 对标 R28）。

interrupt_stream / interrupt_run 的内存注册表行为契约——
无 DB、无 FastAPI，fake agent/dispatcher 直接驱动。
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from backend.api import chat_stream_state as st

pytestmark = pytest.mark.unit


@pytest.fixture()
def clean_registries():
    """测试结束恢复三张注册表原内容（模块级单例，防跨用例污染）。"""
    saved_streams = dict(st._ACTIVE_STREAMS)
    saved_pending = set(st._PENDING_RUN_CANCELLATIONS)
    saved_confirms = dict(st._RUN_CONFIRM_EVENTS)
    st._ACTIVE_STREAMS.clear()
    st._PENDING_RUN_CANCELLATIONS.clear()
    st._RUN_CONFIRM_EVENTS.clear()
    yield st
    st._ACTIVE_STREAMS.clear()
    st._ACTIVE_STREAMS.update(saved_streams)
    st._PENDING_RUN_CANCELLATIONS.clear()
    st._PENDING_RUN_CANCELLATIONS.update(saved_pending)
    st._RUN_CONFIRM_EVENTS.clear()
    st._RUN_CONFIRM_EVENTS.update(saved_confirms)


class _FakeAgent:
    def __init__(self) -> None:
        self.interrupted = False

    def interrupt(self) -> None:
        self.interrupted = True


class _FakeDispatcher:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


def _entry(agent, run_id=None, dispatcher=None) -> Dict[str, Any]:
    e: Dict[str, Any] = {"agent": agent, "cancelled": False}
    if run_id:
        e["run_id"] = run_id
    if dispatcher:
        e["dispatcher"] = dispatcher
    return e


# ---- interrupt_stream ---------------------------------------------------------


def test_interrupt_stream_none_and_missing(clean_registries):
    assert st.interrupt_stream(None) == "none"
    assert st.interrupt_stream("") == "none"
    assert st.interrupt_stream("ghost") == "none"


def test_interrupt_stream_hits_agent_and_marks_cancelled(clean_registries):
    agent = _FakeAgent()
    st._ACTIVE_STREAMS["s1"] = _entry(agent)
    assert st.interrupt_stream("s1") == "stream"
    assert agent.interrupted
    assert st._ACTIVE_STREAMS["s1"]["cancelled"] is True


def test_interrupt_stream_cancels_dispatcher_via_entry(clean_registries):
    agent, disp = _FakeAgent(), _FakeDispatcher()
    st._ACTIVE_STREAMS["s1"] = _entry(agent, run_id="r1", dispatcher=disp)
    assert st.interrupt_stream("s1") == "stream"
    assert disp.cancelled


# ---- interrupt_run ------------------------------------------------------------


def test_interrupt_run_cancels_all_matching_streams(clean_registries):
    a1, a2, d1 = _FakeAgent(), _FakeAgent(), _FakeDispatcher()
    st._ACTIVE_STREAMS["s1"] = _entry(a1, run_id="r1")
    st._ACTIVE_STREAMS["s2"] = _entry(a2, run_id="r1", dispatcher=d1)
    st._ACTIVE_STREAMS["s3"] = _entry(_FakeAgent(), run_id="r2")
    assert st.interrupt_run("r1") == "stream"
    assert a1.interrupted
    assert a2.interrupted
    assert d1.cancelled
    assert st._ACTIVE_STREAMS["s3"]["cancelled"] is False  # 其他 run 不受影响


def test_interrupt_run_unmatched_registers_pending(clean_registries):
    assert st.interrupt_run("r-none") == "pending"
    assert "r-none" in st._PENDING_RUN_CANCELLATIONS


def test_interrupt_run_unmatched_hits_dispatcher_registry(clean_registries, monkeypatch):
    disp = _FakeDispatcher()
    import backend.orchestration.chat_dispatcher as cd

    monkeypatch.setattr(cd, "_ACTIVE_DISPATCHERS", {"r1": disp})
    assert st.interrupt_run("r1") == "stream"
    assert disp.cancelled
    assert "r1" not in st._PENDING_RUN_CANCELLATIONS
