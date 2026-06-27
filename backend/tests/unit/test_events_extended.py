"""
Unit tests for extended LaneEvent enum.

Coverage:
- 8 new events exist with correct string values
- BRANCH_EVENTS and SHIP_EVENTS grouping constants
- LaneEventPayload still serializes the new event names
- Backwards compatibility: existing event names unchanged
"""

from __future__ import annotations

from backend.orchestration.events import (
    BRANCH_EVENTS,
    SHIP_EVENTS,
    LaneEvent,
    LaneEventPayload,
)

# ============================================================================
# New events exist with correct string values
# ============================================================================


class TestNewBranchEvents:
    def test_lane_reconciled(self):
        assert LaneEvent.RECONCILED.value == "lane.reconciled"

    def test_lane_superseded(self):
        assert LaneEvent.SUPERSEDED.value == "lane.superseded"

    def test_branch_stale_against_main(self):
        assert LaneEvent.BRANCH_STALE_AGAINST_MAIN.value == "branch.stale_against_main"

    def test_branch_workspace_mismatch(self):
        assert LaneEvent.BRANCH_WORKSPACE_MISMATCH.value == "branch.workspace_mismatch"


class TestNewShipEvents:
    def test_ship_prepared(self):
        assert LaneEvent.SHIP_PREPARED.value == "ship.prepared"

    def test_ship_commits_selected(self):
        assert LaneEvent.SHIP_COMMITS_SELECTED.value == "ship.commits_selected"

    def test_ship_merged(self):
        assert LaneEvent.SHIP_MERGED.value == "ship.merged"

    def test_ship_pushed_main(self):
        assert LaneEvent.SHIP_PUSHED_MAIN.value == "ship.pushed_main"


# ============================================================================
# Grouping constants
# ============================================================================


class TestGroupingConstants:
    def test_branch_events_includes_branch_events(self):
        assert LaneEvent.BRANCH_STALE_AGAINST_MAIN in BRANCH_EVENTS
        assert LaneEvent.BRANCH_WORKSPACE_MISMATCH in BRANCH_EVENTS

    def test_branch_events_excludes_lifecycle_events(self):
        assert LaneEvent.RECONCILED not in BRANCH_EVENTS
        assert LaneEvent.SUPERSEDED not in BRANCH_EVENTS
        assert LaneEvent.STARTED not in BRANCH_EVENTS

    def test_ship_events_includes_all_ship_events(self):
        assert LaneEvent.SHIP_PREPARED in SHIP_EVENTS
        assert LaneEvent.SHIP_COMMITS_SELECTED in SHIP_EVENTS
        assert LaneEvent.SHIP_MERGED in SHIP_EVENTS
        assert LaneEvent.SHIP_PUSHED_MAIN in SHIP_EVENTS

    def test_ship_events_excludes_lifecycle_events(self):
        assert LaneEvent.STARTED not in SHIP_EVENTS
        assert LaneEvent.MERGED not in SHIP_EVENTS


# ============================================================================
# Payload serialization preserves new event values
# ============================================================================


class TestPayloadSerialization:
    def test_payload_carries_branch_event_value(self):
        payload = LaneEventPayload(
            event=LaneEvent.BRANCH_STALE_AGAINST_MAIN,
            lane_id="lane-1",
            task_id="task-1",
        )
        d = payload.to_dict()
        assert d["event"] == "branch.stale_against_main"

    def test_payload_carries_ship_event_value(self):
        payload = LaneEventPayload(
            event=LaneEvent.SHIP_PUSHED_MAIN,
            lane_id="lane-1",
            task_id="task-1",
        )
        d = payload.to_dict()
        assert d["event"] == "ship.pushed_main"

    def test_payload_carries_reconciled_event_value(self):
        payload = LaneEventPayload(
            event=LaneEvent.RECONCILED,
            lane_id="lane-1",
            task_id="task-1",
        )
        d = payload.to_dict()
        assert d["event"] == "lane.reconciled"


# ============================================================================
# Backwards compatibility: existing event values unchanged
# ============================================================================


class TestBackwardsCompatibility:
    def test_lifecycle_events_unchanged(self):
        assert LaneEvent.STARTED.value == "lane.started"
        assert LaneEvent.READY.value == "lane.ready"
        assert LaneEvent.RUNNING.value == "lane.running"
        assert LaneEvent.BLOCKED.value == "lane.blocked"
        assert LaneEvent.SUCCEEDED.value == "lane.succeeded"
        assert LaneEvent.FAILED.value == "lane.failed"
        assert LaneEvent.STOPPED.value == "lane.stopped"

    def test_git_events_unchanged(self):
        assert LaneEvent.COMMIT_CREATED.value == "lane.commit.created"
        assert LaneEvent.PR_OPENED.value == "lane.pr.opened"
        assert LaneEvent.MERGED.value == "lane.merged"
