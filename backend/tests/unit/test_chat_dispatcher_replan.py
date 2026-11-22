"""M3.2: 失败驱动 re-plan 提示注入。

覆盖：
- 失败终态注入包含 task/goal/error 的提示；同 task 去重；每 run 上限 3
- 解析不到主 agent / inject 返回 False 时安全跳过
- dispatch 集成：子任务失败后 fake 主 agent 收到提示
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from backend.domain import active_agent_registry
from backend.orchestration.chat_dispatcher import ChatDispatcher, ChatTaskState

pytestmark = pytest.mark.unit


class _FakeAgent:
    def __init__(self, accept: bool = True) -> None:
        self.notes: List[str] = []
        self.accept = accept

    def inject_system_note(self, content: str) -> bool:
        if not self.accept:
            return False
        self.notes.append(content)
        return True


class _Queue:
    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []

    def put_nowait(self, item: Dict[str, Any]) -> None:
        self.items.append(item)

    async def put(self, item: Dict[str, Any]) -> None:
        self.items.append(item)


def _make_dispatcher(session_id: str = "sess-1") -> ChatDispatcher:
    return ChatDispatcher(
        stream_id="s1", entry_queue=_Queue(), run_id="orch-replan-1",
        session_id=session_id,
    )


def _failed_state(task_id: str = "t1") -> ChatTaskState:
    return ChatTaskState(
        task_id=task_id,
        agent_id="researcher",
        goal="整理资料",
        status="failed",
        error="boom",
    )


@pytest.fixture(autouse=True)
def _reset_session_resolver():
    active_agent_registry.set_main_agent_session_resolver(None)
    yield
    active_agent_registry.set_main_agent_session_resolver(None)


def test_inject_replan_hint_content():
    agent = _FakeAgent()
    active_agent_registry.set_main_agent_session_resolver(
        lambda sid: agent if sid == "sess-1" else None
    )
    d = _make_dispatcher()
    d._inject_replan_hint(_failed_state("t1"))

    assert len(agent.notes) == 1
    note = agent.notes[0]
    assert "t1" in note
    assert "整理资料" in note
    assert "boom" in note
    assert "add_task_to_plan" in note
    assert "t1" in d._replan_hinted_tasks


def test_inject_once_per_task():
    agent = _FakeAgent()
    active_agent_registry.set_main_agent_session_resolver(lambda sid: agent)
    d = _make_dispatcher()
    d._inject_replan_hint(_failed_state("t1"))
    d._inject_replan_hint(_failed_state("t1"))
    assert len(agent.notes) == 1


def test_inject_limit_per_run():
    agent = _FakeAgent()
    active_agent_registry.set_main_agent_session_resolver(lambda sid: agent)
    d = _make_dispatcher()
    for i in range(5):
        d._inject_replan_hint(_failed_state(f"t{i}"))
    assert len(agent.notes) == 3
    assert len(d._replan_hinted_tasks) == 3


def test_skip_when_no_main_agent():
    d = _make_dispatcher()
    d._inject_replan_hint(_failed_state("t1"))  # resolver 未注册 → 静默跳过
    assert d._replan_hinted_tasks == set()


def test_rejected_note_not_recorded():
    agent = _FakeAgent(accept=False)
    active_agent_registry.set_main_agent_session_resolver(lambda sid: agent)
    d = _make_dispatcher()
    d._inject_replan_hint(_failed_state("t1"))
    assert agent.notes == []
    assert d._replan_hinted_tasks == set()


@pytest.mark.asyncio()
async def test_dispatch_failure_injects_replan_hint(tmp_path, monkeypatch):
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "replan.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()

    agent = _FakeAgent()
    active_agent_registry.set_main_agent_session_resolver(
        lambda sid: agent if sid == "sess-1" else None
    )
    d = _make_dispatcher("sess-1")
    d._semaphore = asyncio.Semaphore(4)

    async def _boom(state: ChatTaskState) -> str:
        raise RuntimeError("rank failure")

    d._run_subagent = _boom

    await d.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g"}])

    assert len(agent.notes) == 1
    assert "rank failure" in agent.notes[0]
    assert d._states["t1"].status == "failed"
