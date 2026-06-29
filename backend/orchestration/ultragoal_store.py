"""
Ultragoal store + leader-only guard for multi-agent orchestration.

Implements the `.omx/ultragoal/` pattern from claw-code:

- Goals are written **only** by the Director role (leader_actor).
- Workers may read goals but every write attempt is denied and logged.
- The ledger is append-only: each create / update / checkpoint / complete
  produces a `LedgerEntry` that is never modified after append.
- Each checkpoint is persisted as a separate JSON file so the trail is
  reproducible from disk alone (no need to re-run the orchestrator).

File layout (when `persist_dir` is set):

    <persist_dir>/
        goals.json                       # canonical snapshot of all goals
        ledger.jsonl                     # append-only audit trail
        check-<goal_id>-<seq>.json       # one file per checkpoint
        worker-write-rejected.log        # every denied worker write

When `persist_dir` is None the store is in-memory only — useful for tests
and ephemeral sessions.

References:
- claw-code `.omx/ultragoal/` directory layout
- claw-code `docs/g006-task-policy-board-verification-map.md` (leader/worker
  separation)
- sage plan: docs/plans/2026-06-26_multi-agent-optimization-from-claw-code.md
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# ============================================================================
# Errors
# ============================================================================


class WorkerWriteDenied(Exception):  # noqa: N818 — short domain-specific name
    """Raised when a non-leader actor attempts to write to the ultragoal store."""

    def __init__(self, actor: str, action: str = "write") -> None:
        super().__init__(
            f"actor {actor!r} is not authorized to {action} ultragoal; "
            f"only the leader may write."
        )
        self.actor = actor
        self.action = action


class DuplicateGoalId(Exception):  # noqa: N818 — short domain-specific name
    """Raised when `create_goal` is called with an existing `goal_id`."""


class GoalNotFound(Exception):  # noqa: N818 — short domain-specific name
    """Raised when an operation references a non-existent goal_id."""


# ============================================================================
# Dataclasses
# ============================================================================


_GoalStatus = Literal["active", "complete", "superseded"]
_LedgerAction = Literal["create", "update", "checkpoint", "supersede", "complete"]
_VALID_GOAL_STATUSES = ("active", "complete", "superseded")
_VALID_LEDGER_ACTIONS = ("create", "update", "checkpoint", "supersede", "complete")


@dataclass
class Ultragoal:
    """A typed, hierarchical goal owned by the Director (leader)."""

    goal_id: str
    title: str
    objective: str
    acceptance_criteria: list[str]
    parent_goal_id: str | None = None
    status: _GoalStatus = "active"
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at: int = field(default_factory=lambda: int(time.time() * 1000))
    sub_goal_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.goal_id or not self.goal_id.strip():
            raise ValueError("goal_id must not be empty")
        if not self.title or not self.title.strip():
            raise ValueError("title must not be empty")
        if not self.objective or not self.objective.strip():
            raise ValueError("objective must not be empty")
        if self.status not in _VALID_GOAL_STATUSES:
            raise ValueError(f"status must be one of {_VALID_GOAL_STATUSES}, got {self.status!r}")
        # Acceptance criteria must contain ≥1 non-blank string.
        cleaned = [c for c in self.acceptance_criteria if c and c.strip()]
        if not cleaned:
            raise ValueError("acceptance_criteria must contain ≥1 non-blank entry")
        self.acceptance_criteria = cleaned

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "title": self.title,
            "objective": self.objective,
            "parent_goal_id": self.parent_goal_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "acceptance_criteria": list(self.acceptance_criteria),
            "sub_goal_ids": list(self.sub_goal_ids),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Ultragoal:
        return cls(
            goal_id=d["goal_id"],
            title=d["title"],
            objective=d["objective"],
            acceptance_criteria=list(d.get("acceptance_criteria", [])),
            parent_goal_id=d.get("parent_goal_id"),
            status=d.get("status", "active"),
            created_at=int(d.get("created_at", time.time() * 1000)),
            updated_at=int(d.get("updated_at", time.time() * 1000)),
            sub_goal_ids=list(d.get("sub_goal_ids", [])),
            metadata=dict(d.get("metadata", {})),
        )


@dataclass
class LedgerEntry:
    """One entry in the append-only audit ledger."""

    entry_id: str
    timestamp: int
    actor: str
    action: _LedgerAction
    goal_id: str
    before: dict[str, Any] | None
    after: dict[str, Any]
    evidence_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.action not in _VALID_LEDGER_ACTIONS:
            raise ValueError(f"action must be one of {_VALID_LEDGER_ACTIONS}, got {self.action!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "action": self.action,
            "goal_id": self.goal_id,
            "before": self.before,
            "after": self.after,
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LedgerEntry:
        return cls(
            entry_id=d["entry_id"],
            timestamp=int(d["timestamp"]),
            actor=d["actor"],
            action=d["action"],
            goal_id=d["goal_id"],
            before=d.get("before"),
            after=d.get("after", {}),
            evidence_refs=list(d.get("evidence_refs", [])),
        )


@dataclass
class Checkpoint:
    """A point-in-time snapshot of a goal's verified state."""

    checkpoint_id: str
    goal_id: str
    created_at: int
    actor: str
    evidence: list[str]
    summary: str
    terminal: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "goal_id": self.goal_id,
            "created_at": self.created_at,
            "actor": self.actor,
            "evidence": list(self.evidence),
            "summary": self.summary,
            "terminal": self.terminal,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Checkpoint:
        return cls(
            checkpoint_id=d["checkpoint_id"],
            goal_id=d["goal_id"],
            created_at=int(d["created_at"]),
            actor=d["actor"],
            evidence=list(d.get("evidence", [])),
            summary=d.get("summary", ""),
            terminal=bool(d.get("terminal", False)),
        )


# ============================================================================
# Store
# ============================================================================


class UltragoalStore:
    """Persistence + audit for `Ultragoal` objects.

    When `persist_dir` is None the store is in-memory only. When set, the
    store writes:
      - `goals.json` — full snapshot of all goals
      - `ledger.jsonl` — append-only
      - `check-<goal_id>-<seq>.json` — one file per checkpoint
      - `worker-write-rejected.log` — append-only
    """

    def __init__(self, persist_dir: Path | str | None = None) -> None:
        self.persist_dir = Path(persist_dir) if persist_dir is not None else None
        self._goals: dict[str, Ultragoal] = {}
        self._ledger: list[LedgerEntry] = []
        self._worker_rejections: list[dict[str, Any]] = []
        self._checkpoint_seq: dict[str, int] = {}
        self._lock = threading.Lock()

        # Reload existing state from disk (if persist_dir is set).
        if self.persist_dir is not None:
            self._reload_from_disk()

    # ------------------------------------------------------------------
    # Goals CRUD
    # ------------------------------------------------------------------

    def create_goal(
        self,
        goal_id: str,
        title: str,
        objective: str,
        acceptance_criteria: list[str],
        parent_goal_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Ultragoal:
        """Create a new goal. Raises DuplicateGoalId if goal_id exists."""
        with self._lock:
            if goal_id in self._goals:
                raise DuplicateGoalId(f"goal_id {goal_id!r} already exists")
            now = int(time.time() * 1000)
            goal = Ultragoal(
                goal_id=goal_id,
                title=title,
                objective=objective,
                acceptance_criteria=list(acceptance_criteria),
                parent_goal_id=parent_goal_id,
                status="active",
                created_at=now,
                updated_at=now,
                metadata=dict(metadata or {}),
            )
            self._goals[goal_id] = goal
            self._append_ledger(
                actor="leader",  # store API always records leader intent
                action="create",
                goal_id=goal_id,
                before=None,
                after=goal.to_dict(),
                evidence_refs=[],
            )
            self._persist_goals()
            return goal

    def get_goal(self, goal_id: str) -> Ultragoal | None:
        return self._goals.get(goal_id)

    def list_active_goals(self) -> list[Ultragoal]:
        return [g for g in self._goals.values() if g.status == "active"]

    def update_goal(
        self,
        goal_id: str,
        actor: str,
        status: _GoalStatus | None = None,
        metadata: dict[str, Any] | None = None,
        sub_goal_ids: list[str] | None = None,
    ) -> Ultragoal:
        """Update mutable fields of a goal. Raises GoalNotFound if missing."""
        with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                raise GoalNotFound(f"goal_id {goal_id!r} not found")
            before = goal.to_dict()
            if status is not None:
                if status not in _VALID_GOAL_STATUSES:
                    raise ValueError(f"invalid status {status!r}")
                goal.status = status
            if metadata is not None:
                goal.metadata.update(metadata)
            if sub_goal_ids is not None:
                goal.sub_goal_ids = list(sub_goal_ids)
            goal.updated_at = int(time.time() * 1000)
            self._append_ledger(
                actor=actor,
                action="update",
                goal_id=goal_id,
                before=before,
                after=goal.to_dict(),
                evidence_refs=[],
            )
            self._persist_goals()
            return goal

    # ------------------------------------------------------------------
    # Checkpoints
    # ------------------------------------------------------------------

    def checkpoint(
        self,
        goal_id: str,
        actor: str,
        evidence: list[str],
        summary: str,
        terminal: bool,
    ) -> Checkpoint:
        """Record a checkpoint for a goal."""
        with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                raise GoalNotFound(f"goal_id {goal_id!r} not found")
            seq = self._checkpoint_seq.get(goal_id, 0) + 1
            self._checkpoint_seq[goal_id] = seq
            ck = Checkpoint(
                checkpoint_id=f"check-{goal_id}-{seq}",
                goal_id=goal_id,
                created_at=int(time.time() * 1000),
                actor=actor,
                evidence=list(evidence),
                summary=summary,
                terminal=terminal,
            )
            self._append_ledger(
                actor=actor,
                action="checkpoint",
                goal_id=goal_id,
                before=self._goals[goal_id].to_dict(),
                after=ck.to_dict(),
                evidence_refs=list(evidence),
            )
            self._persist_checkpoint(ck)
            return ck

    # ------------------------------------------------------------------
    # Ledger
    # ------------------------------------------------------------------

    def read_ledger(self) -> list[LedgerEntry]:
        """Return the full ledger (immutable from the caller's perspective)."""
        return list(self._ledger)

    # ------------------------------------------------------------------
    # Worker write rejections
    # ------------------------------------------------------------------

    def record_worker_write_rejected(
        self,
        actor: str,
        method: str,
        reason: str,
    ) -> None:
        """Append a denial record. Called by UltragoalGuard on every denial."""
        entry = {
            "timestamp": int(time.time() * 1000),
            "actor": actor,
            "method": method,
            "reason": reason,
        }
        with self._lock:
            self._worker_rejections.append(entry)
            self._persist_worker_rejection(entry)

    def read_worker_write_rejections(self) -> list[dict[str, Any]]:
        return list(self._worker_rejections)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _append_ledger(
        self,
        actor: str,
        action: _LedgerAction,
        goal_id: str,
        before: dict[str, Any] | None,
        after: dict[str, Any],
        evidence_refs: list[str],
    ) -> None:
        entry = LedgerEntry(
            entry_id=f"le_{secrets.token_hex(6)}",
            timestamp=int(time.time() * 1000),
            actor=actor,
            action=action,
            goal_id=goal_id,
            before=before,
            after=after,
            evidence_refs=list(evidence_refs),
        )
        self._ledger.append(entry)
        self._persist_ledger_entry(entry)

    # ------------------------------------------------------------------
    # Disk persistence helpers
    # ------------------------------------------------------------------

    def _persist_goals(self) -> None:
        if self.persist_dir is None:
            return
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "goals": {gid: g.to_dict() for gid, g in self._goals.items()},
        }
        (self.persist_dir / "goals.json").write_text(json.dumps(snapshot, sort_keys=True, indent=2))

    def _persist_ledger_entry(self, entry: LedgerEntry) -> None:
        if self.persist_dir is None:
            return
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        with (self.persist_dir / "ledger.jsonl").open("a") as f:
            f.write(json.dumps(entry.to_dict(), sort_keys=True) + "\n")

    def _persist_checkpoint(self, ck: Checkpoint) -> None:
        if self.persist_dir is None:
            return
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        path = self.persist_dir / f"{ck.checkpoint_id}.json"
        path.write_text(json.dumps(ck.to_dict(), sort_keys=True, indent=2))

    def _persist_worker_rejection(self, entry: dict[str, Any]) -> None:
        if self.persist_dir is None:
            return
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        with (self.persist_dir / "worker-write-rejected.log").open("a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")

    def _reload_from_disk(self) -> None:
        """Load existing goals / ledger / rejections / checkpoint seq from disk."""
        assert self.persist_dir is not None
        if not self.persist_dir.exists():
            return
        # goals.json
        goals_file = self.persist_dir / "goals.json"
        if goals_file.exists():
            snapshot = json.loads(goals_file.read_text())
            for gid, gd in snapshot.get("goals", {}).items():
                self._goals[gid] = Ultragoal.from_dict(gd)
        # ledger.jsonl
        ledger_file = self.persist_dir / "ledger.jsonl"
        if ledger_file.exists():
            for line in ledger_file.read_text().splitlines():
                if not line.strip():
                    continue
                self._ledger.append(LedgerEntry.from_dict(json.loads(line)))
        # worker rejections
        rej_file = self.persist_dir / "worker-write-rejected.log"
        if rej_file.exists():
            for line in rej_file.read_text().splitlines():
                if not line.strip():
                    continue
                self._worker_rejections.append(json.loads(line))
        # checkpoint seq (from filenames)
        for path in self.persist_dir.glob("check-*.json"):
            try:
                stem = path.stem
                parts = stem.split("-")
                if len(parts) >= 3:
                    goal_id = "-".join(parts[1:-1])
                    seq = int(parts[-1])
                    current = self._checkpoint_seq.get(goal_id, 0)
                    if seq > current:
                        self._checkpoint_seq[goal_id] = seq
            except (ValueError, IndexError):
                # Skip malformed filenames; they should not happen in normal use.
                continue
                continue


# ============================================================================
# Guard
# ============================================================================


class UltragoalGuard:
    """Leader-only write guard wrapping an `UltragoalStore`.

    Workers may read goals directly from the store. Every mutator goes
    through the guard, which enforces:
      1. actor == leader_actor (else `WorkerWriteDenied`)
      2. the same persistence invariants as the bare store (DuplicateGoalId,
         GoalNotFound, etc.)
    """

    def __init__(
        self,
        store: UltragoalStore,
        leader_actor: str = "leader",
    ) -> None:
        self.store = store
        self.leader_actor = leader_actor

    def assert_can_write(self, actor: str, method: str) -> None:
        """Raise WorkerWriteDenied unless `actor` is the configured leader."""
        if actor != self.leader_actor:
            self.store.record_worker_write_rejected(
                actor=actor,
                method=method,
                reason=f"{method} requires actor=={self.leader_actor!r}",
            )
            raise WorkerWriteDenied(actor, action=method)

    # ------------------------------------------------------------------
    # Mutators — all enforce leader-only writes
    # ------------------------------------------------------------------

    def create_goal(
        self,
        actor: str,
        goal_id: str,
        title: str,
        objective: str,
        acceptance_criteria: list[str],
        parent_goal_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Ultragoal:
        self.assert_can_write(actor, "create_goal")
        return self.store.create_goal(
            goal_id=goal_id,
            title=title,
            objective=objective,
            acceptance_criteria=acceptance_criteria,
            parent_goal_id=parent_goal_id,
            metadata=metadata,
        )

    def update_goal(
        self,
        goal_id: str,
        actor: str,
        status: _GoalStatus | None = None,
        metadata: dict[str, Any] | None = None,
        sub_goal_ids: list[str] | None = None,
    ) -> Ultragoal:
        self.assert_can_write(actor, "update_goal")
        return self.store.update_goal(
            goal_id=goal_id,
            actor=actor,
            status=status,
            metadata=metadata,
            sub_goal_ids=sub_goal_ids,
        )

    def checkpoint(
        self,
        goal_id: str,
        actor: str,
        evidence: list[str],
        summary: str,
        terminal: bool,
    ) -> Checkpoint:
        self.assert_can_write(actor, "checkpoint")
        return self.store.checkpoint(
            goal_id=goal_id,
            actor=actor,
            evidence=evidence,
            summary=summary,
            terminal=terminal,
        )

    def complete(
        self,
        goal_id: str,
        actor: str,
        evidence: list[str] | None = None,
    ) -> Ultragoal:
        """Convenience: mark goal complete + record a terminal checkpoint."""
        self.assert_can_write(actor, "complete")
        goal = self.store.update_goal(goal_id=goal_id, actor=actor, status="complete")
        if evidence:
            self.store.checkpoint(
                goal_id=goal_id,
                actor=actor,
                evidence=evidence,
                summary="complete",
                terminal=True,
            )
        return goal
