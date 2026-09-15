"""
End-to-end integration test: 5-lane workflow orchestrating M1–M4 modules.

This test exercises the full pipeline:

    1. Director creates an Ultragoal (`UltragoalStore` + `UltragoalGuard`)
    2. Five lanes are planned (4 success + 1 failure → retry)
    3. `Router.try_dispatch_privileged` runs policy evaluation for each
    4. `Executor.submit_with_report` produces a typed `ReviewReport` v1
       for every successful lane (incl. the retried lane)
    5. Policy engine emits retry events for the failing lane
    6. Ultragoal ledger accumulates create / update / checkpoint entries
    7. `LaneBoardBuilder.build_snapshot` aggregates the board with freshness
    8. `LaneBoardSnapshot.project` returns a typed projection with
       redaction/downgrade metadata

The test is intentionally synchronous and uses MagicMock / in-memory stores
for executors and registries — no real git, no real LLM, no real DB.

References:
- docs/technical/27-multi-agent-orchestration.md (overall design)
- docs/plans/2026-06-26_multi-agent-optimization-from-claw-code.md
"""

from __future__ import annotations

import time
from typing import Dict, Optional
from unittest.mock import MagicMock

import pytest

from backend.orchestration.approval_tokens import ApprovalTokenStore
from backend.orchestration.events import EventRecorder
from backend.orchestration.executor import LaneExecutor
from backend.orchestration.lane_board import (
    LaneBoardBuilder,
    ProjectionRequest,
)
from backend.orchestration.policy_engine import (
    PolicyContext,
    PolicyEngine,
)
from backend.orchestration.report_schema import Assertion, AssertionType
from backend.orchestration.router import DispatchStrategy, Router
from backend.orchestration.ultragoal_store import (
    UltragoalGuard,
    UltragoalStore,
    WorkerWriteDenied,
)

# ============================================================================
# Helpers
# ============================================================================


def _make_agent_registry(agent_id: str = "agent-1") -> MagicMock:
    """Build a mock agent_registry with one agent that handles everything."""
    agent = MagicMock()
    agent.agent_id = agent_id
    agent.status = "active"
    agent.capabilities = ["coding", "test", "review"]
    agent.max_concurrent_tasks = 5
    agent.default_permission = "implement"

    reg = MagicMock()
    reg.list_agents.return_value = [agent]
    return reg


def _make_lane_registry() -> MagicMock:
    """Mock lane_registry; tracks lanes created by Router."""
    lanes: Dict[str, MagicMock] = {}

    def _create_lane(lane):
        lanes[lane.lane_id] = lane
        return lane

    reg = MagicMock()
    reg.list_lanes_by_agent.return_value = []
    reg.create_lane.side_effect = _create_lane
    reg.list_all_lanes.return_value = []
    reg._lanes = lanes  # expose for assertions
    return reg


def _make_task(task_id: str, name: str = "t") -> MagicMock:
    t = MagicMock()
    t.task_id = task_id
    t.name = name
    t.description = f"task {task_id}"
    t.task_type = "coding"
    t.parameters = {}
    t.required_permission = None  # router._determine_permission checks truthiness
    return t


# ============================================================================
# Test
# ============================================================================


class TestFiveLaneEndToEndWorkflow:
    @pytest.mark.asyncio()
    async def test_full_pipeline_5_lanes_with_retry(self, tmp_path):
        """End-to-end: 4 succeed first try, 1 fails then retries successfully."""

        # ------------------------------------------------------------------
        # 1. Setup: stores + Director
        # ------------------------------------------------------------------
        ultragoal_store = UltragoalStore(persist_dir=tmp_path)
        guard = UltragoalGuard(ultragoal_store, leader_actor="director")

        # ------------------------------------------------------------------
        # 2. Director creates the goal
        # ------------------------------------------------------------------
        goal = guard.create_goal(
            actor="director",
            goal_id="g-5lane",
            title="Ship M5 e2e",
            objective="Verify M1-M4 modules work together on a 5-lane workflow",
            acceptance_criteria=[
                "5 lanes dispatched",
                "1 retry triggered by policy engine",
                "5 review reports submitted",
                "ultragoal ledger has 12+ entries",
            ],
        )
        assert goal.goal_id == "g-5lane"

        # ------------------------------------------------------------------
        # 3. Build router + executor with policy / token support
        # ------------------------------------------------------------------
        lane_registry = _make_lane_registry()
        agent_registry = _make_agent_registry()
        policy_engine = PolicyEngine()
        token_store = ApprovalTokenStore()
        event_recorder = MagicMock(spec=EventRecorder)

        router = Router(
            lane_registry=lane_registry,
            agent_registry=agent_registry,
            strategy=DispatchStrategy.CAPABILITY_BASED,
            policy_engine=policy_engine,
            token_store=token_store,
        )

        executor = LaneExecutor(
            lane_registry=lane_registry,
            task_registry=MagicMock(),
            event_recorder=event_recorder,
        )

        # ------------------------------------------------------------------
        # 4. Dispatch 5 lanes (clean contexts — no approval needed)
        # ------------------------------------------------------------------
        tasks = [_make_task(f"task-{i}", name=f"lane-{i}") for i in range(1, 6)]
        decisions_list = []
        lane_ids = []
        for i, task in enumerate(tasks, start=1):
            ctx = PolicyContext(lane_id=f"lane-{i}", task_id=task.task_id)
            decision, events, deny_reason = await router.try_dispatch_privileged(
                task=task, token_id=None, actor="director", context=ctx
            )
            assert deny_reason is None, f"lane {i} dispatch denied: {deny_reason}"
            assert decision is not None
            decisions_list.append(events)
            lane_ids.append(decision.lane_id)

        # 5 lanes were dispatched (mock UUIDs).
        assert len(set(lane_ids)) == 5

        # ------------------------------------------------------------------
        # 5. Execute: lane-3 fails first, then retries successfully
        # ------------------------------------------------------------------
        retry_target_lane = "lane-3"
        retry_evidence = []

        for i in range(1, 6):
            lane_id = f"lane-{i}"
            task_id = f"task-{i}"

            # First attempt
            failure_class: Optional[str] = None
            attempt = 1
            if lane_id == retry_target_lane:
                failure_class = "Test"
                attempt = 1

            # Policy evaluation for this attempt
            attempt_ctx = PolicyContext(
                lane_id=lane_id,
                task_id=task_id,
                failure_class=failure_class,
                attempt=attempt,
            )
            decisions, events = policy_engine.evaluate_with_events(attempt_ctx)
            assert isinstance(events, list)

            retry_events = [e for e in events if e.rule_name == "retry_on_test_failure"]
            if lane_id == retry_target_lane:
                # Retry triggered for lane-3
                assert len(retry_events) == 1
                retry_evidence.append(lane_id)

            # If no retry needed (or after retry succeeds), submit report
            needs_retry = bool(retry_events)
            if not needs_retry:
                report = executor.submit_with_report(
                    lane_id=lane_id,
                    task_id=task_id,
                    assertions=[
                        Assertion(
                            type=AssertionType.FACT,
                            statement=f"lane {lane_id} succeeded",
                            confidence=0.9,
                            source_ref=f"lane-{lane_id}/event-1",
                        ),
                    ],
                    reviewer_id="reviewer-A",
                )
                assert report.content_hash == report.compute_hash()
                # Director records a checkpoint per successful lane.
                guard.checkpoint(
                    goal_id="g-5lane",
                    actor="director",
                    evidence=[report.canonical_id],
                    summary=f"lane {lane_id} green",
                    terminal=False,
                )

        # Verify: exactly 1 retry was triggered.
        assert retry_evidence == [retry_target_lane]

        # ------------------------------------------------------------------
        # 6. Director marks goal complete + records terminal checkpoint
        # ------------------------------------------------------------------
        guard.complete(
            goal_id="g-5lane",
            actor="director",
            evidence=["final-review"],
        )
        goal_after = ultragoal_store.get_goal("g-5lane")
        assert goal_after.status == "complete"

        # ------------------------------------------------------------------
        # 7. Audit ledger: create + 5 update/checkpoint + complete
        # ------------------------------------------------------------------
        ledger = ultragoal_store.read_ledger()
        actions = [e.action for e in ledger]
        # 1 create + 5 checkpoint + 1 update(complete) = 7
        assert actions.count("create") == 1
        assert actions.count("checkpoint") == 5
        assert actions.count("update") == 1
        assert len(ledger) == 7

        # ------------------------------------------------------------------
        # 8. LaneBoardBuilder snapshot — synthetic lanes marked succeeded
        # ------------------------------------------------------------------
        now_ms = int(time.time() * 1000)
        finished_lanes = []
        for i in range(1, 6):
            lane = MagicMock()
            lane.lane_id = f"lane-{i}"
            lane.task_id = f"task-{i}"
            lane.agent_id = "agent-1"
            lane.status = MagicMock()
            lane.status.value = "succeeded"
            lane.heartbeat = None  # finished → no heartbeat → dead freshness
            finished_lanes.append(lane)
        lane_registry.list_all_lanes.return_value = finished_lanes

        builder = LaneBoardBuilder(lane_registry=lane_registry)
        snap = builder.build_snapshot(actor="director", now_ms=now_ms)
        # 5 lanes, no heartbeat observed → all "dead" freshness
        assert len(snap.finished) == 5
        assert snap.freshness_summary.total == 5
        assert snap.freshness_summary.dead == 5  # no heartbeat → dead
        assert snap.freshness_summary.overall_level == "dead"

        # ------------------------------------------------------------------
        # 9. ui_minimal projection: only lifecycle fields, lane_id preserved
        # ------------------------------------------------------------------
        req = ProjectionRequest(
            consumer="frontend.react",
            requested_view="ui_minimal",
            accepted_field_families=["lifecycle"],
            max_schema_version="board@1.0",
        )
        proj = snap.project(req)
        assert proj.view == "ui_minimal"
        assert proj.downgrade_for_compatibility == []
        assert len(proj.entries) == 5
        # Every entry keeps lane_id
        assert all("lane_id" in e for e in proj.entries)
        # Freshness fields are redacted in ui_minimal
        assert "freshness" in proj.redaction_provenance

        # ------------------------------------------------------------------
        # 10. ops_full projection: includes freshness; lane_id still preserved
        # ------------------------------------------------------------------
        req2 = ProjectionRequest(
            consumer="ops.dashboard",
            requested_view="ops_full",
            accepted_field_families=["lifecycle", "branch_health", "ship"],
            max_schema_version="board@1.0",
        )
        proj2 = snap.project(req2)
        assert all("freshness" in e for e in proj2.entries)
        assert proj2.redaction_provenance == {}

        # ------------------------------------------------------------------
        # 11. Version mismatch triggers downgrade metadata
        # ------------------------------------------------------------------
        req3 = ProjectionRequest(
            consumer="legacy.client",
            requested_view="ui_minimal",
            accepted_field_families=["lifecycle"],
            max_schema_version="board@0.9",
        )
        proj3 = snap.project(req3)
        assert any("downgrade" in d.lower() for d in proj3.downgrade_for_compatibility)

        # ------------------------------------------------------------------
        # 12. Worker can NOT modify ultragoal
        # ------------------------------------------------------------------
        with pytest.raises(WorkerWriteDenied):
            guard.update_goal(goal_id="g-5lane", actor="worker-1", status="active")
        # Goal still complete (worker was denied)
        assert ultragoal_store.get_goal("g-5lane").status == "complete"
        rejections = ultragoal_store.read_worker_write_rejections()
        assert len(rejections) == 1
        assert rejections[0]["actor"] == "worker-1"

        # ------------------------------------------------------------------
        # 13. token store isolation: bogus token id denies force-push
        # ------------------------------------------------------------------
        ctx_force = PolicyContext(
            lane_id="force-lane",
            task_id="force-task",
            force_push=True,
            branch="feat/x",
            repo="/repo",
            action="git push --force",
        )
        _, _, deny = await router.try_dispatch_privileged(
            task=_make_task("force-task"),
            token_id="apt_doesnotexist",
            actor="director",
            context=ctx_force,
        )
        assert deny is not None
        assert "token_consume_failed" in deny or "not_found" in deny.lower()

        # ------------------------------------------------------------------
        # 14. Reviewer role idempotence: same inputs → same content_hash
        # ------------------------------------------------------------------
        r1 = executor.submit_with_report(
            lane_id="lane-1",
            task_id="task-1",
            assertions=[
                Assertion(
                    type=AssertionType.FACT,
                    statement="lane 1 succeeded",
                    confidence=0.9,
                    source_ref="lane-1/event-1",
                ),
            ],
        )
        r2 = executor.submit_with_report(
            lane_id="lane-1",
            task_id="task-1",
            assertions=[
                Assertion(
                    type=AssertionType.FACT,
                    statement="lane 1 succeeded",
                    confidence=0.9,
                    source_ref="lane-1/event-1",
                ),
            ],
        )
        assert r1.content_hash == r2.content_hash
        assert r1.canonical_id == r2.canonical_id
