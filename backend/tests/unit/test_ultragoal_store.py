"""
Unit tests for UltragoalStore + UltragoalGuard.

Coverage:
- Ultragoal dataclass shape + validation (acceptance_criteria ≥ 1)
- LedgerEntry dataclass shape
- Checkpoint dataclass shape
- UltragoalStore: in-memory CRUD on goals + checkpoints + ledger
- UltragoalStore: append-only ledger (entries immutable after append)
- UltragoalStore: file-backed persistence (goals.json + ledger.jsonl)
- UltragoalStore: worker_write_rejected.log captures every denial
- UltragoalGuard: assert_can_write denies non-leader with WorkerWriteDenied
- UltragoalGuard: create / update / checkpoint / complete all enforce leader
- UltragoalGuard: worker creation denied; worker update denied; worker checkpoint denied
- Duplicate goal_id raises DuplicateGoalId
- update on missing goal raises GoalNotFound
"""

from __future__ import annotations

import json

import pytest

from backend.orchestration.ultragoal_store import (
    Checkpoint,
    DuplicateGoalId,
    GoalNotFound,
    LedgerEntry,
    Ultragoal,
    UltragoalGuard,
    UltragoalStore,
    WorkerWriteDenied,
)

# ============================================================================
# Helpers
# ============================================================================


def _goal_kwargs(**overrides) -> dict:
    defaults = {
        "goal_id": "g-001",
        "title": "Ship M3",
        "objective": "Land M3 typed orchestration in sage",
        "acceptance_criteria": ["all unit tests pass", "ruff clean", "mypy clean"],
    }
    defaults.update(overrides)
    return defaults


def _inmem_store() -> UltragoalStore:
    """Build an in-memory store (no file persistence)."""
    return UltragoalStore(persist_dir=None)


# ============================================================================
# Ultragoal dataclass
# ============================================================================


class TestUltragoalDataclass:
    def test_minimal_valid_goal(self):
        g = Ultragoal(**_goal_kwargs())
        assert g.goal_id == "g-001"
        assert g.status == "active"
        assert g.parent_goal_id is None
        assert g.sub_goal_ids == []

    def test_status_validation(self):
        with pytest.raises(ValueError, match="status"):
            Ultragoal(**_goal_kwargs(status="bogus"))

    def test_acceptance_criteria_must_be_nonempty(self):
        with pytest.raises(ValueError, match="acceptance_criteria"):
            Ultragoal(**_goal_kwargs(acceptance_criteria=[]))

    def test_acceptance_criteria_cannot_be_blank_strings(self):
        with pytest.raises(ValueError, match="acceptance_criteria"):
            Ultragoal(**_goal_kwargs(acceptance_criteria=["", "  "]))

    def test_sub_goals_are_initialized_to_empty_list(self):
        g = Ultragoal(**_goal_kwargs())
        assert g.sub_goal_ids == []
        assert isinstance(g.metadata, dict)


# ============================================================================
# LedgerEntry + Checkpoint dataclasses
# ============================================================================


class TestLedgerEntryDataclass:
    def test_minimal_valid_entry(self):
        e = LedgerEntry(
            entry_id="e1",
            timestamp=1000,
            actor="leader",
            action="create",
            goal_id="g-001",
            before=None,
            after={"goal_id": "g-001"},
            evidence_refs=[],
        )
        assert e.actor == "leader"

    def test_action_validation(self):
        with pytest.raises(ValueError, match="action"):
            LedgerEntry(
                entry_id="e1",
                timestamp=1000,
                actor="leader",
                action="delete",  # invalid
                goal_id="g-001",
                before=None,
                after={},
                evidence_refs=[],
            )


class TestCheckpointDataclass:
    def test_minimal_valid_checkpoint(self):
        c = Checkpoint(
            checkpoint_id="check-g-001-1",
            goal_id="g-001",
            created_at=1000,
            actor="leader",
            evidence=["lane-1", "rep-abc"],
            summary="all green",
            terminal=False,
        )
        assert c.terminal is False


# ============================================================================
# Store: in-memory CRUD
# ============================================================================


class TestStoreCRUD:
    def test_create_goal(self):
        s = _inmem_store()
        g = s.create_goal(**_goal_kwargs())
        assert g.goal_id == "g-001"
        assert s.get_goal("g-001") is g

    def test_duplicate_goal_id_raises(self):
        s = _inmem_store()
        s.create_goal(**_goal_kwargs())
        with pytest.raises(DuplicateGoalId):
            s.create_goal(**_goal_kwargs())

    def test_get_unknown_goal_returns_none(self):
        s = _inmem_store()
        assert s.get_goal("nope") is None

    def test_update_goal(self):
        s = _inmem_store()
        s.create_goal(**_goal_kwargs())
        g2 = s.update_goal(
            "g-001",
            actor="leader",
            status="complete",
            metadata={"note": "done"},
        )
        assert g2.status == "complete"
        assert g2.metadata["note"] == "done"

    def test_update_unknown_goal_raises(self):
        s = _inmem_store()
        with pytest.raises(GoalNotFound):
            s.update_goal("nope", actor="leader", status="complete")

    def test_list_active_goals(self):
        s = _inmem_store()
        s.create_goal(**_goal_kwargs(goal_id="g-001"))
        s.create_goal(**_goal_kwargs(goal_id="g-002"))
        s.update_goal("g-002", actor="leader", status="complete")
        active = s.list_active_goals()
        ids = [g.goal_id for g in active]
        assert "g-001" in ids
        assert "g-002" not in ids


# ============================================================================
# Append-only ledger
# ============================================================================


class TestLedgerAppendOnly:
    def test_each_create_appends_ledger_entry(self):
        s = _inmem_store()
        s.create_goal(**_goal_kwargs())
        entries = s.read_ledger()
        assert len(entries) == 1
        assert entries[0].action == "create"
        assert entries[0].goal_id == "g-001"

    def test_update_appends_ledger_entry(self):
        s = _inmem_store()
        s.create_goal(**_goal_kwargs())
        s.update_goal("g-001", actor="leader", status="complete")
        entries = s.read_ledger()
        actions = [e.action for e in entries]
        assert "create" in actions
        assert "update" in actions

    def test_ledger_entry_count_matches_writes(self):
        s = _inmem_store()
        s.create_goal(**_goal_kwargs(goal_id="g-001"))
        s.create_goal(**_goal_kwargs(goal_id="g-002"))
        s.update_goal("g-001", actor="leader", status="complete")
        s.checkpoint("g-001", actor="leader", evidence=["lane-1"], summary="step 1", terminal=False)
        assert len(s.read_ledger()) == 4

    def test_checkpoint_appends_ledger_entry(self):
        s = _inmem_store()
        s.create_goal(**_goal_kwargs())
        s.checkpoint("g-001", actor="leader", evidence=["lane-1"], summary="done", terminal=True)
        entries = s.read_ledger()
        assert any(e.action == "checkpoint" for e in entries)


# ============================================================================
# Guard: leader-only writes
# ============================================================================


class TestGuard:
    def test_leader_create_succeeds(self):
        s = _inmem_store()
        g = UltragoalGuard(s, leader_actor="leader")
        goal = g.create_goal(actor="leader", **_goal_kwargs())
        assert goal.goal_id == "g-001"

    def test_worker_create_denied(self):
        s = _inmem_store()
        g = UltragoalGuard(s, leader_actor="leader")
        with pytest.raises(WorkerWriteDenied):
            g.create_goal(actor="worker-1", **_goal_kwargs())
        # Goal must NOT be persisted.
        assert s.get_goal("g-001") is None

    def test_worker_update_denied(self):
        s = _inmem_store()
        s.create_goal(**_goal_kwargs())
        g = UltragoalGuard(s, leader_actor="leader")
        with pytest.raises(WorkerWriteDenied):
            g.update_goal("g-001", actor="worker-1", status="complete")
        # Status must remain "active".
        assert s.get_goal("g-001").status == "active"

    def test_worker_checkpoint_denied(self):
        s = _inmem_store()
        s.create_goal(**_goal_kwargs())
        g = UltragoalGuard(s, leader_actor="leader")
        with pytest.raises(WorkerWriteDenied):
            g.checkpoint("g-001", actor="worker-1", evidence=["x"], summary="y", terminal=False)

    def test_leader_update_succeeds(self):
        s = _inmem_store()
        s.create_goal(**_goal_kwargs())
        g = UltragoalGuard(s, leader_actor="leader")
        g.update_goal("g-001", actor="leader", status="complete")
        assert s.get_goal("g-001").status == "complete"

    def test_leader_checkpoint_succeeds(self):
        s = _inmem_store()
        s.create_goal(**_goal_kwargs())
        g = UltragoalGuard(s, leader_actor="leader")
        ck = g.checkpoint(
            "g-001", actor="leader", evidence=["lane-1"], summary="first", terminal=False
        )
        assert ck.goal_id == "g-001"
        assert ck.terminal is False

    def test_worker_write_rejection_logged(self):
        s = _inmem_store()
        g = UltragoalGuard(s, leader_actor="leader")
        with pytest.raises(WorkerWriteDenied):
            g.create_goal(actor="worker-x", **_goal_kwargs())
        rejections = s.read_worker_write_rejections()
        assert len(rejections) == 1
        assert rejections[0]["actor"] == "worker-x"


# ============================================================================
# File-backed persistence (tmp dir)
# ============================================================================


class TestFilePersistence:
    def test_persist_and_reload(self, tmp_path):
        s1 = UltragoalStore(persist_dir=tmp_path)
        s1.create_goal(**_goal_kwargs())

        # Reload from disk
        s2 = UltragoalStore(persist_dir=tmp_path)
        g = s2.get_goal("g-001")
        assert g is not None
        assert g.goal_id == "g-001"

    def test_ledger_persists_to_jsonl(self, tmp_path):
        s = UltragoalStore(persist_dir=tmp_path)
        s.create_goal(**_goal_kwargs())
        s.update_goal("g-001", actor="leader", status="complete")

        ledger_file = tmp_path / "ledger.jsonl"
        assert ledger_file.exists()
        lines = ledger_file.read_text().strip().splitlines()
        assert len(lines) == 2
        parsed = [json.loads(line) for line in lines]
        assert parsed[0]["action"] == "create"
        assert parsed[1]["action"] == "update"

    def test_checkpoints_persist(self, tmp_path):
        s = UltragoalStore(persist_dir=tmp_path)
        s.create_goal(**_goal_kwargs())
        s.checkpoint("g-001", actor="leader", evidence=["x"], summary="done", terminal=False)

        check_files = list(tmp_path.glob("check-*.json"))
        assert len(check_files) == 1
        data = json.loads(check_files[0].read_text())
        assert data["goal_id"] == "g-001"

    def test_worker_rejections_persist(self, tmp_path):
        s = UltragoalStore(persist_dir=tmp_path)
        g = UltragoalGuard(s, leader_actor="leader")
        with pytest.raises(WorkerWriteDenied):
            g.create_goal(actor="worker-z", **_goal_kwargs())

        rej_log = tmp_path / "worker-write-rejected.log"
        assert rej_log.exists()
        content = rej_log.read_text()
        assert "worker-z" in content
