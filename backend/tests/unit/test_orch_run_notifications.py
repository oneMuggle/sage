"""M4.3a — 编排 run 终态 / 等待审批通知。

覆盖：
- ``OrchRunNotificationQueue``：按状态映射 kind、bounded 上限、drain 排空
- ``resolve_session_id``：按 run_id 反查 ``orch_runs.session_id``，查不到降级空串
- ``summarize_for_notification``：压成一行 + 限长 120
- ``push_run_notification``：缺省 session_id 时反查、空 run_id 忽略
- ``_finalize_orch_run``：终态通知 + canonical 事件 + 取消态不被覆盖
- ``SubagentEventSink``：等待审批推通知
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_queue():
    """每个用例前后清空进程级通知队列（单例，跨用例会串味）。"""
    from backend.services.orch_run_notifications import get_orch_run_notification_queue

    queue = get_orch_run_notification_queue()
    queue.drain()
    yield
    queue.drain()


def _seed_run(run_id: str = "orch-1", session_id: str = "s-42") -> None:
    """建一条 running 状态的编排 run（conftest 已为每个用例备好临时库）。"""
    from backend.data.orch_run_repo import OrchRun, OrchRunRepository

    OrchRunRepository().upsert(
        OrchRun(
            run_id=run_id,
            session_id=session_id,
            status="running",
            created_at=1,
            plan_json="{}",
        )
    )


def _drained() -> list:
    from backend.services.orch_run_notifications import get_orch_run_notification_queue

    return get_orch_run_notification_queue().drain()


# ---------------------------------------------------------------------------
# 队列本体
# ---------------------------------------------------------------------------


def test_queue_maps_status_to_kind():
    from backend.services.orch_run_notifications import get_orch_run_notification_queue

    queue = get_orch_run_notification_queue()
    for status in ("completed", "failed", "cancelled", "awaiting_approval"):
        queue.push("orch-1", status)
    kinds = [item["kind"] for item in queue.drain()]
    assert kinds == [
        "orch_run_completed",
        "orch_run_failed",
        "orch_run_cancelled",
        "orch_run_awaiting_approval",
    ]


def test_queue_unknown_status_falls_back_to_updated():
    from backend.services.orch_run_notifications import get_orch_run_notification_queue

    queue = get_orch_run_notification_queue()
    queue.push("orch-1", "weird")
    items = queue.drain()
    assert items[0]["kind"] == "orch_run_updated"
    assert items[0]["status"] == "weird"


def test_queue_drain_empties_and_returns_items():
    from backend.services.orch_run_notifications import get_orch_run_notification_queue

    queue = get_orch_run_notification_queue()
    queue.push("orch-1", "completed", session_id="s-1", task_id="task-2", body="done")
    items = queue.drain()
    assert len(items) == 1
    assert queue.size() == 0
    assert queue.drain() == []
    item = items[0]
    assert item["run_id"] == "orch-1"
    assert item["session_id"] == "s-1"
    assert item["task_id"] == "task-2"
    assert item["body"] == "done"
    assert item["created_at"]


def test_queue_is_bounded():
    from backend.services.orch_run_notifications import (
        MAX_ORCH_RUN_NOTIFICATIONS,
        OrchRunNotificationQueue,
    )

    queue = OrchRunNotificationQueue(maxlen=3)
    for i in range(5):
        queue.push(f"orch-{i}", "completed")
    items = queue.drain()
    assert len(items) == 3
    assert MAX_ORCH_RUN_NOTIFICATIONS == 100
    # 只保留最新三条
    assert [item["run_id"] for item in items] == ["orch-2", "orch-3", "orch-4"]


# ---------------------------------------------------------------------------
# session_id 反查 / 摘要
# ---------------------------------------------------------------------------


def test_resolve_session_id_reads_orch_runs():
    from backend.services.orch_run_notifications import resolve_session_id

    _seed_run("orch-1", "s-42")
    assert resolve_session_id("orch-1") == "s-42"


def test_resolve_session_id_degrades_on_missing_or_error(monkeypatch):
    import backend.data.orch_run_repo as repo_mod
    from backend.services import orch_run_notifications as mod

    assert mod.resolve_session_id("orch-nope") == ""
    assert mod.resolve_session_id("") == ""

    def _boom(*args, **kwargs):
        raise RuntimeError("db gone")

    monkeypatch.setattr(repo_mod.OrchRunRepository, "get", _boom)
    assert mod.resolve_session_id("orch-1") == ""


def test_summarize_for_notification_collapses_and_truncates():
    from backend.services.orch_run_notifications import (
        SUMMARY_MAX_CHARS,
        summarize_for_notification,
    )

    assert summarize_for_notification(None) == ""
    assert summarize_for_notification("  a \n b  ") == "a b"
    out = summarize_for_notification("x" * 500)
    assert len(out) == SUMMARY_MAX_CHARS
    assert out.endswith("…")


# ---------------------------------------------------------------------------
# push_run_notification
# ---------------------------------------------------------------------------


def test_push_run_notification_resolves_session_id():
    from backend.services.orch_run_notifications import push_run_notification

    _seed_run("orch-1", "s-42")
    push_run_notification("orch-1", "completed")
    items = _drained()
    assert items[0]["session_id"] == "s-42"
    assert items[0]["kind"] == "orch_run_completed"


def test_push_run_notification_ignores_empty_run_id():
    from backend.services.orch_run_notifications import push_run_notification

    push_run_notification("", "completed")
    assert _drained() == []


# ---------------------------------------------------------------------------
# _finalize_orch_run —— 终态通知 + canonical 事件
# ---------------------------------------------------------------------------


def test_finalize_orch_run_pushes_terminal_notification():
    from backend.api import chat_stream_support as sup

    _seed_run("orch-1", "s-42")
    sup._finalize_orch_run("orch-1", "completed", "all done")

    items = _drained()
    assert len(items) == 1
    assert items[0]["kind"] == "orch_run_completed"
    assert items[0]["run_id"] == "orch-1"
    assert items[0]["session_id"] == "s-42"
    assert items[0]["body"] == "all done"


def test_finalize_orch_run_unknown_status_degrades_to_failed():
    from backend.api import chat_stream_support as sup

    _seed_run("orch-1", "s-42")
    sup._finalize_orch_run("orch-1", "weird-status", "x")

    assert _drained()[0]["kind"] == "orch_run_failed"


def test_finalize_orch_run_keeps_cancelled_state():
    """用户取消端点先写 cancelled；finalize 不能把它覆盖成 failed。"""
    from backend.api import chat_stream_support as sup
    from backend.data.orch_run_repo import OrchRunRepository

    _seed_run("orch-1", "s-42")
    OrchRunRepository().update_status("orch-1", "cancelled")
    sup._finalize_orch_run("orch-1", "failed", "aborted")

    assert _drained()[0]["kind"] == "orch_run_cancelled"


def test_finalize_orch_run_keeps_cancelled_even_when_outcome_completed():
    """DB 终态以取消为准（finalize 只改 running 行），通知不得报 completed。"""
    from backend.api import chat_stream_support as sup
    from backend.data.orch_run_repo import OrchRunRepository

    _seed_run("orch-1", "s-42")
    OrchRunRepository().update_status("orch-1", "cancelled")
    sup._finalize_orch_run("orch-1", "completed", "done")

    assert _drained()[0]["kind"] == "orch_run_cancelled"


@pytest.mark.asyncio()
async def test_finalize_orch_run_publishes_canonical_event(monkeypatch):
    from backend.api import chat_stream_support as sup, orch_run_control

    _seed_run("orch-1", "s-42")

    published = []

    class _Hub:
        async def publish(self, event):
            published.append(event)

    monkeypatch.setattr(orch_run_control, "get_event_hub", lambda: _Hub())
    sup._finalize_orch_run("orch-1", "completed", "done")

    # create_task 排到事件循环上，让它跑完
    for _ in range(5):
        await asyncio.sleep(0)

    assert [e.event_type for e in published] == ["run.completed"]
    assert published[0].run_id == "orch-1"
    assert published[0].payload["status"] == "completed"


def test_finalize_orch_run_survives_missing_event_hub(monkeypatch):
    """EventHub 未装配时终态闭环照常（canonical 事件只是观测通道）。"""
    from backend.api import chat_stream_support as sup, orch_run_control

    _seed_run("orch-1", "s-42")
    monkeypatch.setattr(orch_run_control, "get_event_hub", lambda: None)
    sup._finalize_orch_run("orch-1", "completed", "done")

    assert _drained()[0]["kind"] == "orch_run_completed"


# ---------------------------------------------------------------------------
# SubagentEventSink —— 等待审批
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_subagent_sink_notifies_awaiting_approval():
    from backend.core.legacy.agent_state import AgentEvent, AgentState
    from backend.orchestration.subagent_events import SubagentEventSink

    _seed_run("orch-test", "s-42")

    class _Publisher:
        def __init__(self):
            self.events = []

        async def publish(self, event):
            self.events.append(event)

        __call__ = publish

    publisher = _Publisher()
    sink = SubagentEventSink(
        run_id="orch-test",
        task_id="t1",
        entity_task_id="t1",
        agent_id="researcher",
        goal="调研 X",
        parent_tool_call_id="call-1",
        emit_chat=lambda _payload: None,
        publish_event=publisher,
    )
    await sink(
        AgentEvent(
            state=AgentState.PERMISSION_REQUEST,
            iteration=1,
            agent_id="researcher",
            permission_request={
                "request_id": "req-1",
                "tool_name": "bash",
                "risk": "suspicious",
            },
        )
    )

    items = _drained()
    assert len(items) == 1
    assert items[0]["kind"] == "orch_run_awaiting_approval"
    assert items[0]["run_id"] == "orch-test"
    assert items[0]["session_id"] == "s-42"
    assert items[0]["task_id"] == "t1"
    assert "task.waiting_approval" in [e.event_type for e in publisher.events]
