"""
M5 — Planner LLM injection unit tests.

Covers the previously dead ``llm_client=None`` path:
- mocked LLM → proper task DAG parsed (deps + agent_hint)
- malformed JSON → single-task fallback (never crashes)
- task cap enforcement (MAX_PLAN_TASKS)
- no LLM configured → degraded single-task planning
- forward/cyclic dependencies are dropped (structural DAG guarantee)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from backend.orchestration.planner import MAX_PLAN_TASKS, Planner
from backend.orchestration.task_registry import TaskRegistry
from backend.orchestration.team_registry import TeamRegistry


def _make_planner(llm_client=None) -> Planner:
    return Planner(
        task_registry=TaskRegistry(),
        team_registry=TeamRegistry(),
        llm_client=llm_client,
        auto_configure=False,
    )


def _mock_llm(payload: str) -> object:
    client = AsyncMock()
    client.complete = AsyncMock(return_value=payload)
    return client


class TestPlannerLLMDecomposition:
    @pytest.mark.asyncio()
    async def test_mock_llm_parses_task_dag(self):
        """Valid JSON DAG → tasks with dependencies and agent_hint wired."""
        payload = json.dumps(
            {
                "tasks": [
                    {
                        "id": "t1",
                        "title": "Research topic",
                        "description": "Gather sources about X",
                        "depends_on": [],
                        "agent_hint": "researcher",
                    },
                    {
                        "id": "t2",
                        "title": "Write code",
                        "description": "Implement feature Y",
                        "depends_on": ["t1"],
                        "agent_hint": "coder",
                    },
                    {
                        "id": "t3",
                        "title": "Analyze results",
                        "description": "Summarize findings",
                        "depends_on": ["t2", "t1"],
                    },
                ],
                "reasoning": "research → code → analyze",
            }
        )
        planner = _make_planner(_mock_llm(payload))

        plan = await planner.decompose_request("Build feature X end to end")

        assert len(plan.tasks) == 3
        t1, t2, t3 = plan.tasks
        assert t1.name == "Research topic"
        assert t1.blocked_by == []
        assert t1.parameters.get("agent_hint") == "researcher"
        # Dependencies resolved to REAL task ids of earlier tasks.
        assert t2.blocked_by == [t1.task_id]
        assert set(t3.blocked_by) == {t1.task_id, t2.task_id}
        assert t3.parameters.get("agent_hint") is None
        # Bidirectional relationship back-wired.
        assert set(t1.blocks) == {t2.task_id, t3.task_id}
        assert t2.blocks == [t3.task_id]
        # Team groups all tasks.
        team = TeamRegistry().get_team(plan.team_id)
        assert team is not None
        assert set(team.task_ids) == {t1.task_id, t2.task_id, t3.task_id}
        assert plan.reasoning == "research → code → analyze"
        # Tasks persisted.
        assert TaskRegistry().get_task(t1.task_id) is not None

    @pytest.mark.asyncio()
    async def test_malformed_json_falls_back_to_single_task(self):
        """Unparseable LLM output → single-task fallback, no exception."""
        planner = _make_planner(_mock_llm("this is not JSON {{{"))

        plan = await planner.decompose_request("ship the feature")

        assert len(plan.tasks) == 1
        assert plan.tasks[0].description == "ship the feature"
        assert plan.tasks[0].name.startswith("Execute:")
        assert "fallback" in plan.reasoning.lower()

    @pytest.mark.asyncio()
    async def test_code_fence_wrapped_json_is_accepted(self):
        """LLMs often wrap JSON in ```json fences — must still parse."""
        payload = "```json\n" + json.dumps(
            {"tasks": [{"id": "t1", "title": "Only task", "description": "do it"}]}
        ) + "\n```"
        planner = _make_planner(_mock_llm(payload))

        plan = await planner.decompose_request("goal")

        assert len(plan.tasks) == 1
        assert plan.tasks[0].name == "Only task"

    @pytest.mark.asyncio()
    async def test_task_cap_enforced(self):
        """More than MAX_PLAN_TASKS emitted → truncated to the cap."""
        payload = json.dumps(
            {
                "tasks": [
                    {"id": f"t{i}", "title": f"Task {i}", "description": f"work {i}"}
                    for i in range(1, MAX_PLAN_TASKS + 5)
                ]
            }
        )
        planner = _make_planner(_mock_llm(payload))

        plan = await planner.decompose_request("big goal")

        assert len(plan.tasks) == MAX_PLAN_TASKS

    @pytest.mark.asyncio()
    async def test_forward_and_unknown_dependencies_dropped(self):
        """depends_on referencing later/unknown ids is dropped (DAG-safe)."""
        payload = json.dumps(
            {
                "tasks": [
                    {"id": "t1", "title": "First", "depends_on": ["t2", "nope"]},
                    {"id": "t2", "title": "Second", "depends_on": ["t1"]},
                ]
            }
        )
        planner = _make_planner(_mock_llm(payload))

        plan = await planner.decompose_request("goal")

        first, second = plan.tasks
        # t1's forward ref to t2 and unknown ref dropped entirely.
        assert first.blocked_by == []
        # t2's back-ref to t1 kept.
        assert second.blocked_by == [first.task_id]

    @pytest.mark.asyncio()
    async def test_llm_exception_falls_back(self):
        """LLM transport failure → fallback, planning still works degraded."""
        client = AsyncMock()
        client.complete = AsyncMock(side_effect=RuntimeError("connection refused"))
        planner = _make_planner(client)

        plan = await planner.decompose_request("goal that must not crash")

        assert len(plan.tasks) == 1
        assert plan.tasks[0].description == "goal that must not crash"

    @pytest.mark.asyncio()
    async def test_no_llm_configured_degrades_to_single_task(self):
        """auto_configure with no settings endpoint → fallback planning."""
        planner = Planner(
            task_registry=TaskRegistry(),
            team_registry=TeamRegistry(),
            # auto_configure=True (default); no app_settings seeded → None
        )
        assert planner.llm_client is None

        plan = await planner.decompose_request("degraded goal")

        assert len(plan.tasks) == 1
        assert plan.tasks[0].description == "degraded goal"

    @pytest.mark.asyncio()
    async def test_injected_llm_client_used_over_settings(self, monkeypatch):
        """An injected client wins; settings factory is never consulted."""
        called = {"n": 0}

        def _fail_factory():
            called["n"] += 1
            raise AssertionError("factory must not run when client injected")

        monkeypatch.setattr(
            "backend.orchestration.planner.build_llm_client_from_settings", _fail_factory
        )
        planner = Planner(
            task_registry=TaskRegistry(),
            team_registry=TeamRegistry(),
            llm_client=_mock_llm(json.dumps({"tasks": [{"title": "A", "description": "a"}]})),
        )

        plan = await planner.decompose_request("goal")

        assert len(plan.tasks) == 1
        assert called["n"] == 0

    def test_sanitize_skips_non_dict_entries(self):
        """Garbage list entries are skipped, not crashed on."""
        planner = _make_planner()

        sanitized = planner._sanitize_tasks(
            ["garbage", 42, {"title": "Real", "description": "real work"}]
        )

        assert len(sanitized) == 1
        assert sanitized[0]["name"] == "Real"
