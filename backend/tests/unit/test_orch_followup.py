"""M2.3: 子代理继续对话 —— dispatcher.start_followup + REST 端点。

覆盖：
- parent 不存在/未完成/空内容 → 拒绝
- 成功：生成唯一 fuN id，经 followup_of 后台派发（保留历史）
- 并发达上限（start_background_dispatch 返回 None）→ 拒绝
- 端点：404 无活动 run / 409 不可追问 / 200 成功
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.orchestration.chat_dispatcher import ChatDispatcher, ChatTaskState

pytestmark = pytest.mark.unit


def _make_dispatcher() -> ChatDispatcher:
    class _Q:
        def put_nowait(self, item: Any) -> None:  # noqa: D401 — test stub
            pass

        async def put(self, item: Any) -> None:
            pass

    return ChatDispatcher(stream_id="s1", entry_queue=_Q(), run_id="orch-fu-1")


def _seed_done(dispatcher: ChatDispatcher, task_id: str = "t1") -> None:
    dispatcher._states[task_id] = ChatTaskState(
        task_id=task_id, agent_id="researcher", goal="g", status="done"
    )


def test_followup_rejects_unknown_or_unfinished_parent():
    d = _make_dispatcher()
    assert d.start_followup("nope", "继续") is None

    d._states["t1"] = ChatTaskState(
        task_id="t1", agent_id="researcher", goal="g", status="running"
    )
    assert d.start_followup("t1", "继续") is None


def test_followup_rejects_blank_content():
    d = _make_dispatcher()
    _seed_done(d)
    assert d.start_followup("t1", "   ") is None


def test_followup_dispatches_with_followup_of(monkeypatch):
    d = _make_dispatcher()
    _seed_done(d)
    captured: Dict[str, List[Dict[str, Any]]] = {}

    def _fake_start(tasks):
        captured["tasks"] = tasks
        return object()  # 非 None 即视为已启动

    monkeypatch.setattr(d, "start_background_dispatch", _fake_start)

    result = d.start_followup("t1", "再补充一下第三部分的细节")

    assert result == {"task_id": "fu1"}
    assert captured["tasks"] == [
        {
            "task_id": "fu1",
            "agent_id": "researcher",
            "goal": "再补充一下第三部分的细节",
            "followup_of": "t1",
        }
    ]


def test_followup_generates_unique_ids(monkeypatch):
    d = _make_dispatcher()
    _seed_done(d)
    d._states["fu1"] = ChatTaskState(
        task_id="fu1", agent_id="researcher", goal="g", status="done"
    )
    monkeypatch.setattr(d, "start_background_dispatch", lambda tasks: object())

    result = d.start_followup("t1", "继续")

    assert result == {"task_id": "fu2"}


def test_followup_rejects_when_background_limit_reached(monkeypatch):
    d = _make_dispatcher()
    _seed_done(d)
    monkeypatch.setattr(d, "start_background_dispatch", lambda tasks: None)

    assert d.start_followup("t1", "继续") is None


# ---------------------------------------------------------------------------
# REST 端点
# ---------------------------------------------------------------------------


class _FakeDispatcher:
    def __init__(self, result: Optional[Dict[str, str]]) -> None:
        self.result = result
        self.calls: List[tuple] = []

    def start_followup(self, parent_task_id: str, content: str):
        self.calls.append((parent_task_id, content))
        return self.result


@pytest.fixture()
def client():
    from backend.api.orch_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _patch_dispatchers(monkeypatch, mapping: Dict[str, Any]) -> None:
    from backend.orchestration import chat_dispatcher as cd

    monkeypatch.setattr(cd, "_ACTIVE_DISPATCHERS", mapping)


def test_followup_endpoint_404_without_active_run(client, monkeypatch):
    _patch_dispatchers(monkeypatch, {})

    resp = client.post("/orch/runs/run-1/tasks/t1/followup", json={"content": "继续"})

    assert resp.status_code == 404


def test_followup_endpoint_dispatches(client, monkeypatch):
    fake = _FakeDispatcher({"task_id": "fu1"})
    _patch_dispatchers(monkeypatch, {"run-1": fake})

    resp = client.post("/orch/runs/run-1/tasks/t1/followup", json={"content": "继续"})

    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "ok": True,
        "run_id": "run-1",
        "parent_task_id": "t1",
        "task_id": "fu1",
        "status": "dispatched",
    }
    assert fake.calls == [("t1", "继续")]


def test_followup_endpoint_409_when_unavailable(client, monkeypatch):
    _patch_dispatchers(monkeypatch, {"run-1": _FakeDispatcher(None)})

    resp = client.post("/orch/runs/run-1/tasks/t1/followup", json={"content": "继续"})

    assert resp.status_code == 409


def test_followup_endpoint_rejects_blank_content(client, monkeypatch):
    _patch_dispatchers(monkeypatch, {"run-1": _FakeDispatcher({"task_id": "fu1"})})

    resp = client.post("/orch/runs/run-1/tasks/t1/followup", json={"content": "   "})

    assert resp.status_code == 400
