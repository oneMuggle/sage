"""P0-2 — /interrupt 命中真实运行的 agent（_ACTIVE_STREAMS 注册表）。

旧实现双重断裂: Depends(get_agent) 每次新建空实例 + run_loop 不读标志（Task 1 已修）。
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from httpx import ASGITransport

from backend.core.legacy.agent import SageAgent
from backend.main import app

pytestmark = pytest.mark.unit


@pytest.mark.asyncio()
async def test_endpoint_hits_registered_stream_agent(monkeypatch):
    from backend.api import legacy_routes as lr

    agent = SageAgent()
    monkeypatch.setitem(lr._ACTIVE_STREAMS, "s1", {"agent": agent, "run_id": None})

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/interrupt", json={"stream_id": "s1"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "target": "stream"}
    assert agent.is_interrupted() is True


@pytest.mark.asyncio()
async def test_run_cancel_interrupts_primary_and_dispatcher(monkeypatch):
    """Run-level cancellation reaches both in-process execution owners."""
    from backend.api import legacy_routes as lr
    from backend.api import orch_routes as orch
    from backend.orchestration import chat_dispatcher as cd_mod
    from backend.orchestration.chat_dispatcher import ChatDispatcher

    agent = SageAgent()
    dispatcher = ChatDispatcher(
        stream_id="s3", entry_queue=asyncio.Queue(), run_id="orch-run"
    )
    monkeypatch.setitem(
        lr._ACTIVE_STREAMS,
        "s3",
        {"agent": agent, "run_id": "orch-run", "dispatcher": dispatcher},
    )
    monkeypatch.setitem(cd_mod._ACTIVE_DISPATCHERS, "orch-run", dispatcher)
    monkeypatch.setattr(
        orch.OrchRunRepository,
        "get",
        lambda self, run_id: type(
            "Run", (), {"run_id": run_id, "status": "running"}
        )(),
    )
    monkeypatch.setattr(orch.OrchRunRepository, "update_status", lambda *args: None)

    result = orch.cancel_run("orch-run")

    assert result.status == "cancelled"
    assert agent.is_interrupted() is True
    assert dispatcher._cancelled.is_set()


@pytest.mark.asyncio()
async def test_stream_registration_replays_cancel_before_dispatcher_binding():
    """A cancellation during planning is replayed when dispatcher is bound."""
    from backend.api import legacy_routes as lr
    from backend.orchestration.chat_dispatcher import ChatDispatcher

    agent = SageAgent()
    entry = {"agent": agent, "run_id": "orch-race", "dispatcher": None}
    lr._ACTIVE_STREAMS["race"] = entry
    try:
        assert lr.interrupt_stream("race") == "stream"
        dispatcher = ChatDispatcher(
            stream_id="race", entry_queue=asyncio.Queue(), run_id="orch-race"
        )
        entry["dispatcher"] = dispatcher
        if entry.get("cancelled"):
            dispatcher.cancel()
        assert agent.is_interrupted() is True
        assert dispatcher._cancelled.is_set()
    finally:
        lr._ACTIVE_STREAMS.pop("race", None)


@pytest.mark.asyncio()
async def test_endpoint_bodyless_compat_returns_none():
    """旧调用方不带 body → 200 + target=none（不再误中断随机新实例）。"""
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/interrupt")

    assert resp.status_code == 200
    assert resp.json()["target"] == "none"


@pytest.mark.asyncio()
async def test_interrupt_stream_cancels_dispatcher_in_multi_mode(monkeypatch):
    """multi 模式：中断主 agent 的同时 cancel 关联 dispatcher。"""
    from backend.api import legacy_routes as lr
    from backend.orchestration import chat_dispatcher as cd_mod
    from backend.orchestration.chat_dispatcher import ChatDispatcher

    agent = SageAgent()
    dispatcher = ChatDispatcher(
        stream_id="s2", entry_queue=asyncio.Queue(), run_id="orch-x"
    )
    monkeypatch.setitem(lr._ACTIVE_STREAMS, "s2", {"agent": agent, "run_id": "orch-x"})
    monkeypatch.setitem(cd_mod._ACTIVE_DISPATCHERS, "orch-x", dispatcher)

    assert lr.interrupt_stream("s2") == "stream"
    assert agent.is_interrupted() is True
    assert dispatcher._cancelled.is_set()


def test_interrupt_stream_unknown_or_missing_returns_none():
    from backend.api import legacy_routes as lr

    assert lr.interrupt_stream("ghost-stream") == "none"
    assert lr.interrupt_stream(None) == "none"
