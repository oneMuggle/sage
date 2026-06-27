"""
Unit tests for Router integration with PolicyEngine + ApprovalTokenStore.

Coverage:
- Constructor backwards-compatible (no policy_engine / no token_store)
- dispatch_with_policy without policy_engine falls back to route_task
- dispatch_with_policy with policy_engine emits decision events
- try_dispatch_privileged denies when approval required but no token_store
- try_dispatch_privileged consumes token when valid
- try_dispatch_privileged denies when token missing or invalid
- Privileged actions (force_push, cross_branch_merge) require valid token
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.orchestration.approval_tokens import ApprovalTokenStore
from backend.orchestration.models import Task
from backend.orchestration.policy_engine import (
    PolicyContext,
    PolicyDecisionKind,
    PolicyEngine,
)
from backend.orchestration.router import DispatchStrategy, Router

# ============================================================================
# Helpers
# ============================================================================


def _task(**overrides) -> Task:
    defaults = {
        "task_id": "task-1",
        "name": "t",
        "description": "d",
        "task_type": "coding",
    }
    defaults.update(overrides)
    return Task(**defaults)


def _make_router(
    *,
    with_policy: bool = False,
    with_token_store: bool = False,
) -> Router:
    """Build a Router with mocked registries + optional policy/token deps."""
    lane_registry = MagicMock()
    lane_registry.list_lanes_by_agent.return_value = []
    lane_registry.create_lane.return_value = MagicMock(lane_id="lane-1")
    lane_registry.list_all_lanes.return_value = []

    agent = MagicMock()
    agent.agent_id = "agent-1"
    agent.status = "active"
    agent.capabilities = ["coding"]
    agent.max_concurrent_tasks = 1
    agent.default_permission = "implement"

    agent_registry = MagicMock()
    agent_registry.list_agents.return_value = [agent]

    return Router(
        lane_registry=lane_registry,
        agent_registry=agent_registry,
        strategy=DispatchStrategy.CAPABILITY_BASED,
        policy_engine=PolicyEngine() if with_policy else None,
        token_store=ApprovalTokenStore() if with_token_store else None,
    )


# ============================================================================
# Backwards compatibility
# ============================================================================


class TestBackwardsCompatibility:
    def test_router_without_policy_engine_constructs(self):
        r = _make_router()
        assert r.policy_engine is None

    def test_router_without_token_store_constructs(self):
        r = _make_router()
        assert r.token_store is None


# ============================================================================
# dispatch_with_policy
# ============================================================================


class TestDispatchWithPolicy:
    @pytest.mark.asyncio()
    async def test_no_policy_engine_falls_back_to_route_task(self):
        r = _make_router(with_policy=False)
        ctx = PolicyContext(lane_id="lane-1", task_id="task-1")
        decision, events = await r.dispatch_with_policy(_task(), ctx)
        assert decision is not None
        assert events == []

    @pytest.mark.asyncio()
    async def test_with_policy_engine_emits_no_events_for_clean_context(self):
        r = _make_router(with_policy=True)
        ctx = PolicyContext(lane_id="lane-1", task_id="task-1")
        decision, events = await r.dispatch_with_policy(_task(), ctx)
        assert decision is not None
        assert events == []

    @pytest.mark.asyncio()
    async def test_with_policy_engine_emits_retry_event_on_test_failure(self):
        r = _make_router(with_policy=True)
        ctx = PolicyContext(lane_id="lane-1", task_id="task-1", failure_class="Test", attempt=1)
        decision, events = await r.dispatch_with_policy(_task(), ctx)
        retry_events = [e for e in events if e.kind == PolicyDecisionKind.RETRY]
        assert len(retry_events) == 1
        assert retry_events[0].rule_name == "retry_on_test_failure"


# ============================================================================
# try_dispatch_privileged
# ============================================================================


class TestTryDispatchPrivileged:
    @pytest.mark.asyncio()
    async def test_no_token_store_denies_approval_actions(self):
        r = _make_router(with_policy=True, with_token_store=False)
        ctx = PolicyContext(lane_id="lane-1", task_id="task-1", force_push=True, branch="feat/x")
        decision, events, deny_reason = await r.try_dispatch_privileged(
            task=_task(), token_id=None, actor="alice", context=ctx
        )
        assert decision is None
        assert deny_reason is not None
        assert "token_store" in deny_reason.lower() or "approval" in deny_reason.lower()

    @pytest.mark.asyncio()
    async def test_clean_context_dispatches_normally(self):
        r = _make_router(with_policy=True, with_token_store=True)
        ctx = PolicyContext(lane_id="lane-1", task_id="task-1")
        decision, events, deny_reason = await r.try_dispatch_privileged(
            task=_task(), token_id=None, actor="alice", context=ctx
        )
        assert deny_reason is None
        assert decision is not None

    @pytest.mark.asyncio()
    async def test_force_push_without_token_denied(self):
        r = _make_router(with_policy=True, with_token_store=True)
        ctx = PolicyContext(lane_id="lane-1", task_id="task-1", force_push=True, branch="feat/x")
        decision, events, deny_reason = await r.try_dispatch_privileged(
            task=_task(), token_id=None, actor="alice", context=ctx
        )
        assert decision is None
        assert deny_reason is not None

    @pytest.mark.asyncio()
    async def test_force_push_with_valid_token_granted(self):
        r = _make_router(with_policy=True, with_token_store=True)
        ctx = PolicyContext(
            lane_id="lane-1",
            task_id="task-1",
            force_push=True,
            branch="feat/x",
            repo="/repo",
            action="git push --force-with-lease",
        )
        token = r.token_store.issue(
            approver="alice",
            policy_exception="approval_for_force_push",
            action="git push --force-with-lease",
            scope_repo="/repo",
            scope_branch="feat/x",
        )
        decision, events, deny_reason = await r.try_dispatch_privileged(
            task=_task(), token_id=token.token_id, actor="alice", context=ctx
        )
        assert deny_reason is None
        assert decision is not None
        # Token must be consumed.
        assert token.consumed_count == 1

    @pytest.mark.asyncio()
    async def test_force_push_with_invalid_token_denied(self):
        r = _make_router(with_policy=True, with_token_store=True)
        ctx = PolicyContext(
            lane_id="lane-1",
            task_id="task-1",
            force_push=True,
            branch="feat/x",
            repo="/repo",
            action="git push --force-with-lease",
        )
        # Issue a token for a DIFFERENT branch
        token = r.token_store.issue(
            approver="alice",
            policy_exception="approval_for_force_push",
            action="git push --force-with-lease",
            scope_repo="/repo",
            scope_branch="feat/different",
        )
        decision, events, deny_reason = await r.try_dispatch_privileged(
            task=_task(), token_id=token.token_id, actor="alice", context=ctx
        )
        assert decision is None
        assert deny_reason is not None
        assert token.consumed_count == 0  # not consumed

    @pytest.mark.asyncio()
    async def test_cross_branch_merge_without_token_denied(self):
        r = _make_router(with_policy=True, with_token_store=True)
        ctx = PolicyContext(
            lane_id="lane-1",
            task_id="task-1",
            crossed_branches=True,
            branch="release/win7",
            repo="/repo",
            action="merge_to_release",
        )
        decision, events, deny_reason = await r.try_dispatch_privileged(
            task=_task(), token_id=None, actor="alice", context=ctx
        )
        assert decision is None
        assert deny_reason is not None

    @pytest.mark.asyncio()
    async def test_cross_branch_merge_with_token_granted(self):
        r = _make_router(with_policy=True, with_token_store=True)
        ctx = PolicyContext(
            lane_id="lane-1",
            task_id="task-1",
            crossed_branches=True,
            branch="release/win7",
            repo="/repo",
            action="merge_to_release",
        )
        token = r.token_store.issue(
            approver="alice",
            policy_exception="approval_for_cross_branch_merge",
            action="merge_to_release",
            scope_repo="/repo",
            scope_branch="release/win7",
        )
        decision, events, deny_reason = await r.try_dispatch_privileged(
            task=_task(), token_id=token.token_id, actor="alice", context=ctx
        )
        assert deny_reason is None
        assert decision is not None
        assert token.consumed_count == 1

    @pytest.mark.asyncio()
    async def test_unknown_token_denied(self):
        r = _make_router(with_policy=True, with_token_store=True)
        ctx = PolicyContext(
            lane_id="lane-1",
            task_id="task-1",
            force_push=True,
            branch="feat/x",
            repo="/repo",
            action="git push --force-with-lease",
        )
        decision, events, deny_reason = await r.try_dispatch_privileged(
            task=_task(),
            token_id="apt_doesnotexist",
            actor="alice",
            context=ctx,
        )
        assert decision is None
        assert deny_reason is not None
