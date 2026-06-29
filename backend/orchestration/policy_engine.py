"""
Policy Engine for multi-agent orchestration.

Translates runtime context (lane state, heartbeat, failure class) into a set of
typed `PolicyDecision` actions. Each decision becomes a `PolicyDecisionEvent`
that is emitted to the event stream for audit + downstream consumers.

References:
- claw-code `rust/crates/runtime/src/policy_engine.rs` (PolicyDecisionEvent,
  evaluate_with_events, priority-sorted flattened actions)
- sage plan: docs/plans/2026-06-26_multi-agent-optimization-from-claw-code.md

Design:
- Pure logic: no I/O, no DB, no global state
- 12 declarative rules; each rule is a small predicate
- `evaluate_with_events` returns (decisions, events) so callers can persist
  events without recomputing decisions.
- Approval decisions allocate a fresh approval token placeholder id (the real
  store lives in `approval_tokens.py`).
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PolicyDecisionKind(str, Enum):
    """Categories of policy decisions."""

    RETRY = "retry"
    REBASE = "rebase"
    MERGE = "merge"
    ESCALATE = "escalate"
    STALE_CLEANUP = "stale_cleanup"
    APPROVAL = "approval"


# ============================================================================
# Input
# ============================================================================


@dataclass
class PolicyContext:
    """Snapshot of runtime state used by the policy engine.

    All fields are optional strings/booleans so callers can build the context
    from heterogeneous sources (LaneHeartbeat, FailureReport, action payload).
    """

    lane_id: str
    task_id: str
    attempt: int = 1

    # Failure context
    failure_class: str | None = None  # "Test" / "Compile" / "TrustGate" / ...
    heartbeat_status: str | None = None  # "healthy" / "stalled" / "dead" / "transport_dead"
    lane_status: str | None = None  # "green" / "red" / "blocked" / ...

    # Action context
    action: str | None = None
    branch: str = "main"
    repo: str = ""
    commit: str = ""
    crossed_branches: bool = False
    force_push: bool = False
    upstream_reconciled: bool = False
    workspace_mismatch: bool = False

    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Output
# ============================================================================


@dataclass
class PolicyDecision:
    """A single in-process decision (no timestamp, no serialization)."""

    rule_name: str
    priority: int
    kind: PolicyDecisionKind
    explanation: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyDecisionEvent:
    """A persistable, auditable event for the event stream.

    Mirrors claw-code's `PolicyDecisionEvent` (rule_name, priority, kind,
    explanation, approval_token_id) with extra lane_id for cross-lane queries.
    """

    rule_name: str
    priority: int
    kind: PolicyDecisionKind
    explanation: str
    lane_id: str
    decided_at: int
    approval_token_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to plain dict (JSON-compatible)."""
        return {
            "rule_name": self.rule_name,
            "priority": self.priority,
            "kind": self.kind.value,
            "explanation": self.explanation,
            "lane_id": self.lane_id,
            "decided_at": self.decided_at,
            "approval_token_id": self.approval_token_id,
            "metadata": dict(self.metadata),
        }


# ============================================================================
# Engine
# ============================================================================


def _new_token_id() -> str:
    """Allocate a fresh approval token placeholder id."""
    return f"apt_{secrets.token_hex(8)}"


class PolicyEngine:
    """Evaluates a `PolicyContext` and produces typed decisions.

    The engine holds no state and is safe to share across lanes / sessions.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, ctx: PolicyContext) -> list[PolicyDecision]:
        """Run all matching rules, return decisions sorted by priority ascending."""
        raw: list[PolicyDecision] = []
        raw.extend(self._retry_rules(ctx))
        raw.extend(self._rebase_rules(ctx))
        raw.extend(self._escalate_rules(ctx))
        raw.extend(self._stale_cleanup_rules(ctx))
        raw.extend(self._merge_rules(ctx))
        raw.extend(self._approval_rules(ctx))
        return sorted(raw, key=lambda d: d.priority)

    def evaluate_with_events(
        self, ctx: PolicyContext
    ) -> tuple[list[PolicyDecision], list[PolicyDecisionEvent]]:
        """Run `evaluate` and convert each decision into a persistable event.

        Returns (decisions, events). Each decision maps to exactly one event;
        priority ordering is preserved in both lists.
        """
        decisions = self.evaluate(ctx)
        now = int(time.time() * 1000)
        events: list[PolicyDecisionEvent] = []
        for d in decisions:
            token_id: str | None = None
            if d.kind == PolicyDecisionKind.APPROVAL:
                # Each approval decision must carry a token id (even if it is a
                # placeholder — the real token is minted by ApprovalTokenStore).
                token_id = _new_token_id()
            events.append(
                PolicyDecisionEvent(
                    rule_name=d.rule_name,
                    priority=d.priority,
                    kind=d.kind,
                    explanation=d.explanation,
                    lane_id=ctx.lane_id,
                    decided_at=now,
                    approval_token_id=token_id,
                    metadata=dict(d.metadata),
                )
            )
        return decisions, events

    # ------------------------------------------------------------------
    # Rule groups — order in source matches evaluation order, but the public
    # `evaluate` method always returns priority-sorted output.
    # ------------------------------------------------------------------

    def _retry_rules(self, ctx: PolicyContext) -> list[PolicyDecision]:
        out: list[PolicyDecision] = []
        # Rule 1: retry on test failure (attempt <= 3)
        if ctx.failure_class == "Test" and ctx.attempt <= 3:
            out.append(
                PolicyDecision(
                    rule_name="retry_on_test_failure",
                    priority=20,
                    kind=PolicyDecisionKind.RETRY,
                    explanation=(
                        f"Test failure on attempt {ctx.attempt}; "
                        "retry up to 3 attempts before escalation."
                    ),
                )
            )
        # Rule 2: retry on compile failure (attempt <= 3)
        if ctx.failure_class == "Compile" and ctx.attempt <= 3:
            out.append(
                PolicyDecision(
                    rule_name="retry_on_compile_failure",
                    priority=21,
                    kind=PolicyDecisionKind.RETRY,
                    explanation=(
                        f"Compile failure on attempt {ctx.attempt}; "
                        "retry up to 3 attempts before escalation."
                    ),
                )
            )
        return out

    def _rebase_rules(self, ctx: PolicyContext) -> list[PolicyDecision]:
        out: list[PolicyDecision] = []
        # Rule 3: rebase on branch divergence
        if ctx.failure_class == "BranchDivergence":
            out.append(
                PolicyDecision(
                    rule_name="rebase_on_branch_divergence",
                    priority=15,
                    kind=PolicyDecisionKind.REBASE,
                    explanation=("Branch has diverged from base; rebase required before retry."),
                )
            )
        return out

    def _escalate_rules(self, ctx: PolicyContext) -> list[PolicyDecision]:
        out: list[PolicyDecision] = []
        # Rule 4: escalate on trust gate (no retry, no auto)
        if ctx.failure_class == "TrustGate":
            out.append(
                PolicyDecision(
                    rule_name="escalate_on_trust_gate",
                    priority=5,
                    kind=PolicyDecisionKind.ESCALATE,
                    explanation="Trust gate triggered; human approval required.",
                )
            )
        # Rule 5: escalate on repeated failure (attempt >= 3)
        if ctx.attempt >= 3:
            out.append(
                PolicyDecision(
                    rule_name="escalate_on_repeated_failure",
                    priority=10,
                    kind=PolicyDecisionKind.ESCALATE,
                    explanation=(f"Attempt {ctx.attempt} exceeds retry threshold; escalate."),
                )
            )
        # Rule 11: prompt delivery failure → escalate immediately (no retry)
        if ctx.failure_class == "PromptDelivery":
            out.append(
                PolicyDecision(
                    rule_name="escalate_on_prompt_delivery",
                    priority=3,
                    kind=PolicyDecisionKind.ESCALATE,
                    explanation=("Prompt delivery failure; no auto-retry, escalate."),
                )
            )
        return out

    def _stale_cleanup_rules(self, ctx: PolicyContext) -> list[PolicyDecision]:
        out: list[PolicyDecision] = []
        # Rule 6: heartbeat dead
        if ctx.heartbeat_status == "dead":
            out.append(
                PolicyDecision(
                    rule_name="stale_cleanup_on_heartbeat_dead",
                    priority=8,
                    kind=PolicyDecisionKind.STALE_CLEANUP,
                    explanation=("Lane heartbeat is dead beyond threshold; cleanup."),
                )
            )
        # Rule 7: transport dead
        if ctx.heartbeat_status == "transport_dead":
            out.append(
                PolicyDecision(
                    rule_name="stale_cleanup_on_transport_dead",
                    priority=7,
                    kind=PolicyDecisionKind.STALE_CLEANUP,
                    explanation=("Lane transport layer is dead; cleanup required."),
                )
            )
        # Rule 12: workspace mismatch
        if ctx.workspace_mismatch:
            out.append(
                PolicyDecision(
                    rule_name="stale_cleanup_on_workspace_mismatch",
                    priority=2,
                    kind=PolicyDecisionKind.STALE_CLEANUP,
                    explanation=(
                        "Worktree path does not match declared scope_path; " "refuse to start lane."
                    ),
                )
            )
        return out

    def _merge_rules(self, ctx: PolicyContext) -> list[PolicyDecision]:
        out: list[PolicyDecision] = []
        # Rule 8: merge on lane green + upstream reconciled
        if ctx.lane_status == "green" and ctx.upstream_reconciled:
            out.append(
                PolicyDecision(
                    rule_name="merge_on_lane_green_and_reconciled",
                    priority=30,
                    kind=PolicyDecisionKind.MERGE,
                    explanation=("Lane is green and upstream reconciled; merge is allowed."),
                )
            )
        return out

    def _approval_rules(self, ctx: PolicyContext) -> list[PolicyDecision]:
        out: list[PolicyDecision] = []
        # Rule 9: force push requires approval
        if ctx.force_push:
            out.append(
                PolicyDecision(
                    rule_name="approval_for_force_push",
                    priority=1,
                    kind=PolicyDecisionKind.APPROVAL,
                    explanation=(
                        f"Force push requested on {ctx.branch}; " "explicit approval required."
                    ),
                )
            )
        # Rule 10: cross-branch merge requires approval
        if ctx.crossed_branches:
            out.append(
                PolicyDecision(
                    rule_name="approval_for_cross_branch_merge",
                    priority=1,
                    kind=PolicyDecisionKind.APPROVAL,
                    explanation=(
                        f"Cross-branch merge requested (current={ctx.branch}); "
                        "approval required."
                    ),
                )
            )
        return out
