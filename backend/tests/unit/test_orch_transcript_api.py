"""``GET /orch/runs/{run_id}/tasks/{task_id}/transcript`` 测试（M1）。

覆盖：
- 按 seq 升序返回消息、next_seq / has_more
- after_seq 续传 + limit 分页
- 未知 run/task 返回空列表（轮询友好）
- limit 上限校验
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.orch_run_control import configure, router
from backend.data.orch_transcript_repo import OrchTranscriptRepository, TaskTranscriptMessage
from backend.orchestration.event_hub import EventHub
from backend.orchestration.snapshot_store import SnapshotStore


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    configure(SnapshotStore(), EventHub())
    return TestClient(app)


def _seed(count: int = 5) -> OrchTranscriptRepository:
    repo = OrchTranscriptRepository()
    for i in range(1, count + 1):
        repo.append(
            TaskTranscriptMessage(
                run_id="run-1",
                task_id="t1",
                seq=i,
                role="assistant",
                message_type="assistant",
                content=f"msg-{i}",
                created_at=1_700_000_000_000 + i,
            )
        )
    return repo


def test_returns_messages_in_seq_order(client):
    _seed()

    resp = client.get("/orch/runs/run-1/tasks/t1/transcript")

    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "run-1"
    assert data["task_id"] == "t1"
    assert [m["seq"] for m in data["messages"]] == [1, 2, 3, 4, 5]
    assert data["messages"][0]["content"] == "msg-1"
    assert data["next_seq"] == 5
    assert data["has_more"] is False


def test_after_seq_and_limit_pagination(client):
    _seed()

    resp = client.get("/orch/runs/run-1/tasks/t1/transcript?after_seq=2&limit=2")
    data = resp.json()
    assert [m["seq"] for m in data["messages"]] == [3, 4]
    assert data["next_seq"] == 4
    assert data["has_more"] is True

    resp = client.get("/orch/runs/run-1/tasks/t1/transcript?after_seq=4&limit=2")
    data = resp.json()
    assert [m["seq"] for m in data["messages"]] == [5]
    assert data["next_seq"] == 5
    assert data["has_more"] is False


def test_unknown_run_returns_empty(client):
    resp = client.get("/orch/runs/nope/tasks/t1/transcript")

    assert resp.status_code == 200
    data = resp.json()
    assert data["messages"] == []
    assert data["next_seq"] == 0
    assert data["has_more"] is False


def test_limit_is_capped(client):
    resp = client.get("/orch/runs/run-1/tasks/t1/transcript?limit=9999")

    assert resp.status_code == 422


def test_tool_args_round_trips_as_json(client):
    repo = OrchTranscriptRepository()
    repo.append(
        TaskTranscriptMessage(
            run_id="run-1",
            task_id="t1",
            seq=1,
            role="assistant",
            message_type="tool_call",
            tool_name="web_search",
            tool_call_id="call-1",
            tool_args='{"q": "sage"}',
            created_at=1_700_000_000_000,
        )
    )

    resp = client.get("/orch/runs/run-1/tasks/t1/transcript")
    message = resp.json()["messages"][0]
    assert message["tool_name"] == "web_search"
    assert message["tool_args"] == {"q": "sage"}
