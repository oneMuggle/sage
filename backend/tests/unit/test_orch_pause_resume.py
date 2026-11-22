"""M2.5: 任务/run 级暂停与恢复。

覆盖：
- ChatDispatcher.pause_task/resume_task 状态与事件；幂等；仅 running 可暂停
- pause_run/resume_run 批量计数
- SageAgent.run_loop 暂停闸门（暂停期间不发 LLM 请求，恢复后继续）
- REST 端点 404/409/200
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse
from backend.orchestration.chat_dispatcher import ChatDispatcher, ChatTaskState
from backend.orchestration.pause_state import PauseState

pytestmark = pytest.mark.unit


class _Queue:
    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []

    def put_nowait(self, item: Dict[str, Any]) -> None:
        self.items.append(item)

    async def put(self, item: Dict[str, Any]) -> None:
        self.items.append(item)


def _make_dispatcher() -> tuple[ChatDispatcher, _Queue]:
    queue = _Queue()
    d = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-pause-1")
    return d, queue


def _seed(d: ChatDispatcher, task_id: str = "t1", status: str = "running") -> None:
    d._states[task_id] = ChatTaskState(
        task_id=task_id, agent_id="a", goal="g", status=status
    )


def test_pause_and_resume_task_transitions():
    d, queue = _make_dispatcher()
    _seed(d)

    assert d.pause_task("t1") is True
    assert d._states["t1"].status == "paused"
    assert d._pause_state_for("t1").paused is True
    assert queue.items[-1]["status"] == "paused"

    # 幂等：已暂停再暂停 → False
    assert d.pause_task("t1") is False

    assert d.resume_task("t1") is True
    assert d._states["t1"].status == "running"
    assert d._pause_state_for("t1").paused is False
    assert queue.items[-1]["status"] == "running"

    # 幂等：运行中再恢复 → False
    assert d.resume_task("t1") is False


def test_pause_task_requires_running():
    d, _ = _make_dispatcher()
    _seed(d, "t1", "queued")
    assert d.pause_task("t1") is False
    assert d.pause_task("nope") is False


def test_resume_requires_paused():
    d, _ = _make_dispatcher()
    _seed(d, "t1", "running")
    assert d.resume_task("t1") is False


def test_pause_run_and_resume_run_counts():
    d, _ = _make_dispatcher()
    _seed(d, "t1", "running")
    _seed(d, "t2", "running")
    _seed(d, "t3", "paused")
    d._pause_state_for("t3").request_pause()

    assert d.pause_run() == 2
    assert d.resume_run() == 3
    assert all(d._states[t].status == "running" for t in ("t1", "t2", "t3"))


@pytest.mark.asyncio()
async def test_run_loop_blocks_while_paused():
    pause_state = PauseState()
    pause_state.request_pause()
    agent = SageAgent(pause_state=pause_state)
    calls = {"n": 0}

    async def _chat(messages, tools=None, tool_choice=None, retry_callback=None):
        calls["n"] += 1
        return LLMResponse(content="done")

    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(side_effect=_chat)
    messages = [{"role": "user", "content": "开始"}]
    events = []

    async def _drive() -> None:
        async for evt in agent.run_loop(messages, max_iterations=2):
            events.append(evt)

    driver = asyncio.create_task(_drive())
    await asyncio.sleep(0.05)
    assert calls["n"] == 0  # 暂停中未发起 LLM 请求

    pause_state.request_resume()
    await asyncio.wait_for(driver, timeout=3)
    assert calls["n"] >= 1
    assert any(e.state == AgentState.DONE for e in events)


# ---------------------------------------------------------------------------
# REST 端点
# ---------------------------------------------------------------------------


class _FakeDispatcher:
    def __init__(self) -> None:
        self.calls: List[str] = []
        self.pause_result = True
        self.resume_result = True
        self.pause_run_result = 2
        self.resume_run_result = 2

    def pause_task(self, task_id: str) -> bool:
        self.calls.append(f"pause:{task_id}")
        return self.pause_result

    def resume_task(self, task_id: str) -> bool:
        self.calls.append(f"resume:{task_id}")
        return self.resume_result

    def pause_run(self) -> int:
        self.calls.append("pause_run")
        return self.pause_run_result

    def resume_run(self) -> int:
        self.calls.append("resume_run")
        return self.resume_run_result


@pytest.fixture()
def client():
    from backend.api.orch_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _patch(monkeypatch, mapping: Dict[str, Any]) -> None:
    from backend.orchestration import chat_dispatcher as cd

    monkeypatch.setattr(cd, "_ACTIVE_DISPATCHERS", mapping)


def test_pause_task_endpoint_404(client, monkeypatch):
    _patch(monkeypatch, {})
    resp = client.post("/orch/runs/run-1/tasks/t1/pause")
    assert resp.status_code == 404


def test_pause_task_endpoint_409(client, monkeypatch):
    fake = _FakeDispatcher()
    fake.pause_result = False
    _patch(monkeypatch, {"run-1": fake})
    resp = client.post("/orch/runs/run-1/tasks/t1/pause")
    assert resp.status_code == 409


def test_pause_task_endpoint_ok(client, monkeypatch):
    fake = _FakeDispatcher()
    _patch(monkeypatch, {"run-1": fake})
    resp = client.post("/orch/runs/run-1/tasks/t1/pause")
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "run_id": "run-1",
        "task_id": "t1",
        "status": "paused",
    }
    assert fake.calls == ["pause:t1"]


def test_resume_task_endpoint_ok(client, monkeypatch):
    fake = _FakeDispatcher()
    _patch(monkeypatch, {"run-1": fake})
    resp = client.post("/orch/runs/run-1/tasks/t1/resume")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"
    assert fake.calls == ["resume:t1"]


def test_pause_run_endpoint_ok(client, monkeypatch):
    fake = _FakeDispatcher()
    _patch(monkeypatch, {"run-1": fake})
    resp = client.post("/orch/runs/run-1/pause")
    assert resp.status_code == 200
    assert resp.json()["affected"] == 2


def test_pause_run_endpoint_409_when_none_running(client, monkeypatch):
    fake = _FakeDispatcher()
    fake.pause_run_result = 0
    _patch(monkeypatch, {"run-1": fake})
    resp = client.post("/orch/runs/run-1/pause")
    assert resp.status_code == 409


def test_resume_run_endpoint_ok(client, monkeypatch):
    fake = _FakeDispatcher()
    _patch(monkeypatch, {"run-1": fake})
    resp = client.post("/orch/runs/run-1/resume")
    assert resp.status_code == 200
    assert resp.json()["affected"] == 2
