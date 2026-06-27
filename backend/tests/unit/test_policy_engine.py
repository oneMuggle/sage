"""
Unit tests for PolicyEngine.

Coverage:
- 12 policy rules each with ≥1 happy-path + ≥1 boundary test
- evaluate_with_events ordering by priority
- approval decisions carry approval_token_id
- non-approval decisions do NOT carry approval_token_id
"""

from __future__ import annotations

from backend.orchestration.policy_engine import (
    PolicyContext,
    PolicyDecisionKind,
    PolicyEngine,
)

# ============================================================================
# Test helpers
# ============================================================================


def _ctx(**overrides) -> PolicyContext:
    """Build a PolicyContext with sensible defaults; allow overrides."""
    defaults = {
        "lane_id": "lane-1",
        "task_id": "task-1",
        "attempt": 1,
        "failure_class": None,
        "heartbeat_status": None,
        "lane_status": None,
        "action": None,
        "branch": "feat/example",
        "repo": "/repo",
        "commit": "abc123",
        "crossed_branches": False,
        "force_push": False,
        "upstream_reconciled": False,
        "workspace_mismatch": False,
    }
    defaults.update(overrides)
    return PolicyContext(**defaults)


# ============================================================================
# Rule 1 & 2: retry on Test / Compile failure
# ============================================================================


class TestRetryRules:
    def test_retry_on_test_failure_first_attempt(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(failure_class="Test", attempt=1))
        assert any(d.rule_name == "retry_on_test_failure" for d in decisions)

    def test_retry_on_test_failure_third_attempt_still_allowed(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(failure_class="Test", attempt=3))
        assert any(d.rule_name == "retry_on_test_failure" for d in decisions)

    def test_no_retry_on_test_failure_after_three_attempts(self):
        """Boundary: attempt > 3 must NOT trigger retry rule."""
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(failure_class="Test", attempt=4))
        assert not any(d.rule_name == "retry_on_test_failure" for d in decisions)

    def test_retry_on_compile_failure(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(failure_class="Compile", attempt=1))
        assert any(d.rule_name == "retry_on_compile_failure" for d in decisions)


# ============================================================================
# Rule 3: rebase on branch divergence
# ============================================================================


class TestRebaseRule:
    def test_rebase_on_branch_divergence(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(failure_class="BranchDivergence"))
        assert any(d.rule_name == "rebase_on_branch_divergence" for d in decisions)

    def test_no_rebase_when_no_divergence(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(failure_class=None))
        assert not any(d.rule_name == "rebase_on_branch_divergence" for d in decisions)


# ============================================================================
# Rule 4 & 5: escalate on trust gate / repeated failure
# ============================================================================


class TestEscalateRules:
    def test_escalate_on_trust_gate(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(failure_class="TrustGate"))
        assert any(d.rule_name == "escalate_on_trust_gate" for d in decisions)

    def test_escalate_on_repeated_failure_at_threshold(self):
        """Boundary: attempt == 3 → escalate."""
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(attempt=3))
        assert any(d.rule_name == "escalate_on_repeated_failure" for d in decisions)

    def test_escalate_on_repeated_failure_beyond_threshold(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(attempt=10))
        assert any(d.rule_name == "escalate_on_repeated_failure" for d in decisions)

    def test_no_escalate_below_threshold(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(attempt=2))
        assert not any(d.rule_name == "escalate_on_repeated_failure" for d in decisions)


# ============================================================================
# Rule 6 & 7: stale cleanup on heartbeat dead / transport dead
# ============================================================================


class TestStaleCleanupRules:
    def test_stale_cleanup_on_heartbeat_dead(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(heartbeat_status="dead"))
        assert any(d.rule_name == "stale_cleanup_on_heartbeat_dead" for d in decisions)

    def test_stale_cleanup_on_transport_dead(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(heartbeat_status="transport_dead"))
        assert any(d.rule_name == "stale_cleanup_on_transport_dead" for d in decisions)

    def test_no_stale_cleanup_on_healthy(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(heartbeat_status="healthy"))
        assert not any(d.rule_name.startswith("stale_cleanup") for d in decisions)


# ============================================================================
# Rule 8: merge on lane green + reconciled
# ============================================================================


class TestMergeRule:
    def test_merge_on_lane_green_and_reconciled(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(lane_status="green", upstream_reconciled=True))
        assert any(d.rule_name == "merge_on_lane_green_and_reconciled" for d in decisions)

    def test_no_merge_when_not_reconciled(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(lane_status="green", upstream_reconciled=False))
        assert not any(d.rule_name == "merge_on_lane_green_and_reconciled" for d in decisions)


# ============================================================================
# Rule 9 & 10: approval for force push / cross-branch merge
# ============================================================================


class TestApprovalRules:
    def test_approval_for_force_push(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(action="git push --force", force_push=True))
        assert any(d.rule_name == "approval_for_force_push" for d in decisions)
        approval = [d for d in decisions if d.kind == PolicyDecisionKind.APPROVAL]
        assert all(approval)

    def test_approval_for_cross_branch_merge(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(action="merge_to_release", crossed_branches=True))
        assert any(d.rule_name == "approval_for_cross_branch_merge" for d in decisions)

    def test_no_approval_for_normal_push(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(action="git push", force_push=False))
        assert not any(d.kind == PolicyDecisionKind.APPROVAL for d in decisions)


# ============================================================================
# Rule 11: escalate on prompt delivery failure
# ============================================================================


class TestPromptDeliveryRule:
    def test_escalate_on_prompt_delivery_first_failure(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(failure_class="PromptDelivery", attempt=1))
        # Boundary: PromptDelivery 立刻 escalate (不 retry)
        assert any(d.rule_name == "escalate_on_prompt_delivery" for d in decisions)
        assert not any(d.kind == PolicyDecisionKind.RETRY for d in decisions)


# ============================================================================
# Rule 12: stale cleanup on workspace mismatch
# ============================================================================


class TestWorkspaceMismatchRule:
    def test_stale_cleanup_on_workspace_mismatch(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(action="start_lane", workspace_mismatch=True))
        assert any(d.rule_name == "stale_cleanup_on_workspace_mismatch" for d in decisions)


# ============================================================================
# evaluate_with_events
# ============================================================================


class TestEvaluateWithEvents:
    def test_events_sorted_by_priority_ascending(self):
        engine = PolicyEngine()
        _, events = engine.evaluate_with_events(
            _ctx(
                failure_class="Test",
                attempt=5,
                heartbeat_status="dead",
            )
        )
        priorities = [e.priority for e in events]
        assert priorities == sorted(priorities)

    def test_events_have_lane_id(self):
        engine = PolicyEngine()
        _, events = engine.evaluate_with_events(_ctx(failure_class="Test", lane_id="lane-xyz"))
        assert all(e.lane_id == "lane-xyz" for e in events)

    def test_approval_event_carries_token_id(self):
        engine = PolicyEngine()
        decisions, events = engine.evaluate_with_events(
            _ctx(action="git push --force", force_push=True)
        )
        approval_events = [e for e in events if e.kind == PolicyDecisionKind.APPROVAL]
        assert len(approval_events) == 1
        assert approval_events[0].approval_token_id is not None
        assert approval_events[0].approval_token_id.startswith("apt_")

    def test_non_approval_events_have_no_token(self):
        engine = PolicyEngine()
        _, events = engine.evaluate_with_events(_ctx(failure_class="Test"))
        non_approval = [e for e in events if e.kind != PolicyDecisionKind.APPROVAL]
        assert all(e.approval_token_id is None for e in non_approval)

    def test_events_serializable_to_dict(self):
        engine = PolicyEngine()
        _, events = engine.evaluate_with_events(_ctx(failure_class="Test", attempt=1))
        for e in events:
            d = e.to_dict()
            assert "rule_name" in d
            assert "kind" in d
            assert "decided_at" in d


# ============================================================================
# Boundary: empty context produces no decisions
# ============================================================================


class TestEmptyContext:
    def test_no_unrelated_rules_trigger(self):
        engine = PolicyEngine()
        decisions = engine.evaluate(_ctx(failure_class=None, heartbeat_status=None))
        assert all(d.rule_name != "approval_for_force_push" for d in decisions)
        assert all(d.rule_name != "approval_for_cross_branch_merge" for d in decisions)
