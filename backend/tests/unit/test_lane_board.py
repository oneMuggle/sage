"""
Unit tests for LaneBoardBuilder + Capability Negotiation.

Coverage:
- LaneFreshness: fresh / stale / dead thresholds (boundary tests)
- FreshnessSummary: aggregate counts + overall_level (worst-of-three)
- BoardEntry + LaneBoardSnapshot shape + to_dict
- LaneBoardBuilder.build_snapshot groups by active/blocked/finished
- CapabilityManifest: emitter / schema_versions / projection_views
- ProjectionRequest + BoardProjection
- UnsupportedView raises on unknown view
- downgrade_for_compatibility populated when max_schema_version < producer
- redaction_provenance populated when field omitted
- lane_id is always preserved in projections (never omitted)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from backend.orchestration.lane_board import (
    BoardProjection,
    CapabilityManifest,
    FreshnessSummary,
    LaneBoardBuilder,
    LaneBoardSnapshot,
    LaneFreshness,
    ProjectionRequest,
    UnsupportedViewError as UnsupportedView,  # noqa: N818
)

# ============================================================================
# Helpers
# ============================================================================


def _now_ms() -> int:
    return int(time.time() * 1000)


def _make_lane(
    lane_id: str,
    status: str = "running",
    heartbeat_at: int | None = None,
    task_id: str = "task-1",
    agent_id: str | None = "agent-1",
):
    """Build a MagicMock lane with the minimal attributes LaneBoardBuilder reads."""
    lane = MagicMock()
    lane.lane_id = lane_id
    lane.task_id = task_id
    lane.agent_id = agent_id
    lane.status = MagicMock()
    lane.status.value = status
    # heartbeat may be None or carry last_heartbeat_at
    if heartbeat_at is None:
        lane.heartbeat = None
    else:
        hb = MagicMock()
        hb.last_heartbeat_at = heartbeat_at
        lane.heartbeat = hb
    return lane


def _builder(lanes: list | None = None) -> LaneBoardBuilder:
    """Build a builder backed by a mocked lane_registry."""
    reg = MagicMock()
    reg.list_all_lanes.return_value = lanes or []
    return LaneBoardBuilder(lane_registry=reg)


# ============================================================================
# LaneFreshness
# ============================================================================


class TestLaneFreshness:
    def test_fresh_within_threshold(self):
        f = LaneFreshness.from_age(lane_id="lane-1", age_ms=1000)
        assert f.level == "fresh"
        assert f.reasons == []

    def test_stale_when_between_thresholds(self):
        f = LaneFreshness.from_age(lane_id="lane-1", age_ms=60_000)
        assert f.level == "stale"
        assert "age_exceeds_fresh_threshold" in f.reasons

    def test_dead_when_beyond_dead_threshold(self):
        f = LaneFreshness.from_age(lane_id="lane-1", age_ms=600_000)
        assert f.level == "dead"
        assert "age_exceeds_stale_threshold" in f.reasons

    def test_no_heartbeat_marks_dead(self):
        f = LaneFreshness.from_age(lane_id="lane-1", age_ms=None)
        assert f.level == "dead"
        assert "no_heartbeat_observed" in f.reasons

    def test_age_ms_is_none_when_no_heartbeat(self):
        f = LaneFreshness.from_age(lane_id="lane-1", age_ms=None)
        assert f.age_ms is None
        assert f.last_heartbeat_at is None


# ============================================================================
# FreshnessSummary
# ============================================================================


class TestFreshnessSummary:
    def test_aggregate_counts(self):
        s = FreshnessSummary.from_entries(
            [
                LaneFreshness.from_age(lane_id="l1", age_ms=100),
                LaneFreshness.from_age(lane_id="l2", age_ms=60_000),
                LaneFreshness.from_age(lane_id="l3", age_ms=600_000),
            ]
        )
        assert s.total == 3
        assert s.fresh == 1
        assert s.stale == 1
        assert s.dead == 1

    def test_overall_level_worst_of_three(self):
        s = FreshnessSummary.from_entries(
            [
                LaneFreshness.from_age(lane_id="l1", age_ms=100),
                LaneFreshness.from_age(lane_id="l2", age_ms=100),
                LaneFreshness.from_age(lane_id="l3", age_ms=600_000),
            ]
        )
        assert s.overall_level == "dead"

    def test_overall_level_stale_when_no_dead(self):
        s = FreshnessSummary.from_entries(
            [
                LaneFreshness.from_age(lane_id="l1", age_ms=100),
                LaneFreshness.from_age(lane_id="l2", age_ms=60_000),
            ]
        )
        assert s.overall_level == "stale"


# ============================================================================
# LaneBoardBuilder — snapshot
# ============================================================================


class TestLaneBoardBuilder:
    def test_empty_lane_list_yields_empty_groups(self):
        b = _builder([])
        snap = b.build_snapshot(actor="system")
        assert isinstance(snap, LaneBoardSnapshot)
        assert snap.active == []
        assert snap.blocked == []
        assert snap.finished == []

    def test_groups_lanes_by_status(self):
        now = _now_ms()
        lanes = [
            _make_lane("lane-1", status="running", heartbeat_at=now),
            _make_lane("lane-2", status="blocked", heartbeat_at=now),
            _make_lane("lane-3", status="succeeded", heartbeat_at=now),
        ]
        b = _builder(lanes)
        snap = b.build_snapshot(actor="system")
        assert [e.lane_id for e in snap.active] == ["lane-1"]
        assert [e.lane_id for e in snap.blocked] == ["lane-2"]
        assert [e.lane_id for e in snap.finished] == ["lane-3"]

    def test_entry_includes_freshness(self):
        now = _now_ms()
        lanes = [_make_lane("lane-1", status="running", heartbeat_at=now)]
        b = _builder(lanes)
        snap = b.build_snapshot(actor="system")
        e = snap.active[0]
        assert e.freshness.level == "fresh"

    def test_snapshot_to_dict_round_trip(self):
        now = _now_ms()
        lanes = [_make_lane("lane-1", status="running", heartbeat_at=now)]
        b = _builder(lanes)
        snap = b.build_snapshot(actor="system")
        d = snap.to_dict()
        assert d["schema_version"] == "1.0"
        assert "active" in d
        assert "freshness_summary" in d


# ============================================================================
# Capability negotiation
# ============================================================================


class TestCapabilityManifest:
    def test_default_manifest_lists_supported_views(self):
        m = CapabilityManifest.default_for_board_v1()
        assert "ui_minimal" in m.projection_views
        assert "ops_full" in m.projection_views
        assert "board@1.0" in m.schema_versions


class TestProjection:
    def _snap(self) -> LaneBoardSnapshot:
        now = _now_ms()
        lanes = [_make_lane("lane-1", status="running", heartbeat_at=now)]
        return _builder(lanes).build_snapshot(actor="system")

    def test_unsupported_view_raises(self):
        snap = self._snap()
        req = ProjectionRequest(
            consumer="frontend.react",
            requested_view="ops_huge",
            accepted_field_families=["lifecycle"],
        )
        with pytest.raises(UnsupportedView):
            snap.project(req)

    def test_supported_view_returns_projection(self):
        snap = self._snap()
        req = ProjectionRequest(
            consumer="frontend.react",
            requested_view="ui_minimal",
            accepted_field_families=["lifecycle"],
        )
        proj = snap.project(req)
        assert isinstance(proj, BoardProjection)
        assert proj.view == "ui_minimal"

    def test_lane_id_always_preserved_in_projection(self):
        snap = self._snap()
        req = ProjectionRequest(
            consumer="frontend.react",
            requested_view="ui_minimal",
            accepted_field_families=[],
        )
        proj = snap.project(req)
        assert all("lane_id" in e for e in proj.entries)

    def test_downgrade_for_compatibility_when_version_mismatch(self):
        snap = self._snap()
        req = ProjectionRequest(
            consumer="old.client",
            requested_view="ui_minimal",
            max_schema_version="board@0.9",
            accepted_field_families=["lifecycle"],
        )
        proj = snap.project(req)
        assert any(
            "version" in d.lower() or "schema" in d.lower()
            for d in proj.downgrade_for_compatibility
        )

    def test_no_downgrade_when_version_matches(self):
        snap = self._snap()
        req = ProjectionRequest(
            consumer="new.client",
            requested_view="ui_minimal",
            max_schema_version="board@1.0",
            accepted_field_families=["lifecycle"],
        )
        proj = snap.project(req)
        assert proj.downgrade_for_compatibility == []

    def test_redaction_provenance_populated_when_fields_omitted(self):
        snap = self._snap()
        req = ProjectionRequest(
            consumer="frontend.react",
            requested_view="ui_minimal",
            accepted_field_families=["lifecycle"],
        )
        proj = snap.project(req)
        assert len(proj.redaction_provenance) >= 1
        for _field, reason in proj.redaction_provenance.items():
            assert reason
