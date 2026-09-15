"""
M5 — Orchestration lane creation API tests.

Real registries (SQLite temp DB via conftest), mocked LLM. Covers:
- POST /orchestration/lanes → planner decomposition → lanes listed with
  initial state / agent binding / planner source metadata
- GET endpoints reflect created lanes (state, agent, metadata, events)
- cancel still works on a created lane
- empty goal → 400; unknown agent → 400
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

SEED_AGENTS = {"primary", "researcher", "coder", "memory_manager"}


@pytest.fixture()
def _no_llm(monkeypatch):
    """Force the degraded planner path (no endpoint settings)."""
    monkeypatch.setattr(
        "backend.orchestration.planner.build_llm_client_from_settings", lambda: None
    )


@pytest.fixture()
def mock_planner_llm(monkeypatch):
    """Planner LLM emitting a two-task DAG."""
    payload = json.dumps(
        {
            "tasks": [
                {"id": "t1", "title": "Research", "description": "research work"},
                {
                    "id": "t2",
                    "title": "Implement",
                    "description": "coding work",
                    "depends_on": ["t1"],
                },
            ],
            "reasoning": "research then implement",
        }
    )
    client = AsyncMock()
    client.complete = AsyncMock(return_value=payload)
    monkeypatch.setattr(
        "backend.orchestration.planner.build_llm_client_from_settings", lambda: client
    )
    return client


@pytest.fixture()
def _stub_background_exec(monkeypatch):
    """Isolate lane lifecycle from B2 wait=false background execution.

    Wave 3 B2 (P2-10) made ``POST /lanes`` (wait=false) fire execution in the
    background via ``asyncio.create_task``. These M5 tests assert lanes stay in
    ``created`` after creation — without an execution-phase LLM the background
    executor fails lanes to ``failed`` on the next event-loop turn, making the
    lifecycle assertions flaky/order-dependent. Stub the executor so
    create → list / detail / events / cancel remain deterministic.
    """

    async def _noop_exec(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "backend.api.orchestration_router._execute_plan_lanes", _noop_exec
    )


class TestCreateLanes:
    @pytest.mark.usefixtures("_no_llm", "_stub_background_exec")
    async def test_create_lane_degraded_single_task(self, client):
        """No LLM → single fallback lane, bound to a seeded agent."""
        resp = await client.post(
            "/api/v1/orchestration/lanes", json={"goal": "Summarize the wiki"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["team_id"]
        assert len(body["lanes"]) == 1
        assert len(body["tasks"]) == 1

        lane = body["lanes"][0]
        assert lane["status"] == "created"  # initial state — not executed yet
        assert lane["agent_id"] in SEED_AGENTS
        assert lane["metadata"]["source"] == "planner"
        assert lane["metadata"]["goal"] == "Summarize the wiki"

        task = body["tasks"][0]
        assert task["status"] == "created"
        assert task["team_id"] == body["team_id"]

    @pytest.mark.usefixtures("mock_planner_llm", "_stub_background_exec")
    async def test_create_lanes_with_mock_llm_two_tasks(self, client):
        """LLM DAG → two lanes, dependency wired between tasks."""
        resp = await client.post(
            "/api/v1/orchestration/lanes", json={"goal": "Build feature Z"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["lanes"]) == 2
        tasks = body["tasks"]
        assert [t["name"] for t in tasks] == ["Research", "Implement"]
        # Second task depends on the first (real ids).
        assert tasks[1]["blocked_by"] == [tasks[0]["task_id"]]

    @pytest.mark.usefixtures("_no_llm", "_stub_background_exec")
    async def test_created_lane_visible_in_get_endpoints(self, client):
        """GET list/detail/events reflect the created lane."""
        created = (
            await client.post("/api/v1/orchestration/lanes", json={"goal": "visible goal"})
        ).json()
        lane_id = created["lanes"][0]["lane_id"]

        # List — includes the lane with metadata + agent.
        listing = (await client.get("/api/v1/orchestration/lanes")).json()
        listed = next(item for item in listing if item["lane_id"] == lane_id)
        assert listed["metadata"]["source"] == "planner"
        assert listed["agent_id"] in SEED_AGENTS
        assert listed["status"] == "created"

        # Detail.
        detail = (await client.get(f"/api/v1/orchestration/lanes/{lane_id}")).json()
        assert detail["lane_id"] == lane_id

        # Events — lane.started recorded at creation.
        events = (await client.get(f"/api/v1/orchestration/lanes/{lane_id}/events")).json()
        assert any(e["event_type"] == "lane.started" for e in events)

    @pytest.mark.usefixtures("_no_llm", "_stub_background_exec")
    async def test_cancel_created_lane(self, client):
        """Cancellation still works on planner-created lanes."""
        created = (
            await client.post("/api/v1/orchestration/lanes", json={"goal": "to cancel"})
        ).json()
        lane_id = created["lanes"][0]["lane_id"]

        resp = await client.post(
            f"/api/v1/orchestration/lanes/{lane_id}/cancel", json={"reason": "changed_mind"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

        # Second cancel → 409 terminal.
        again = await client.post(f"/api/v1/orchestration/lanes/{lane_id}/cancel", json={})
        assert again.status_code == 409

    @pytest.mark.usefixtures("mock_planner_llm", "_stub_background_exec")
    async def test_explicit_agent_pins_all_lanes(self, client):
        """?agent=researcher → every lane bound to researcher."""
        resp = await client.post(
            "/api/v1/orchestration/lanes", json={"goal": "research stuff", "agent": "researcher"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["lanes"]) == 2
        assert all(lane["agent_id"] == "researcher" for lane in body["lanes"])

    @pytest.mark.usefixtures("_no_llm")
    async def test_empty_goal_400(self, client):
        resp = await client.post("/api/v1/orchestration/lanes", json={"goal": "   "})
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"]

    @pytest.mark.usefixtures("_no_llm")
    async def test_unknown_agent_400(self, client):
        resp = await client.post(
            "/api/v1/orchestration/lanes", json={"goal": "g", "agent": "ghost-agent"}
        )
        assert resp.status_code == 400
        assert "ghost-agent" in resp.json()["detail"]
