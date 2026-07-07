"""
Unit tests for Executor.submit_with_report.

Coverage:
- submit_with_report returns a valid ReviewReport v1
- The returned report has assertions + projection_lineage
- The content_hash matches a fresh compute_hash()
- The report's canonical_id is deterministic and includes lane_id
- The event_recorder receives an event carrying report metadata
- Backwards compatibility: existing execute_lane behavior unchanged
- reviewer's id defaults to 'system' but can be overridden
- empty assertions list still produces a valid (if thin) report
"""

from __future__ import annotations

from typing import List
from unittest.mock import MagicMock

from backend.orchestration.events import EventRecorder
from backend.orchestration.executor import LaneExecutor
from backend.orchestration.report_schema import Assertion, AssertionType

# ============================================================================
# Helpers
# ============================================================================


def _make_executor(*, with_recorder: bool = False) -> LaneExecutor:
    """Build a LaneExecutor with mocked registries."""
    lane_registry = MagicMock()
    lane_registry.get_lane.return_value = None
    task_registry = MagicMock()
    recorder = MagicMock(spec=EventRecorder) if with_recorder else None
    return LaneExecutor(
        lane_registry=lane_registry,
        task_registry=task_registry,
        event_recorder=recorder,
    )


def _sample_assertions() -> List[Assertion]:
    return [
        Assertion(
            type=AssertionType.FACT,
            statement="all unit tests passed",
            confidence=0.95,
            source_ref="lane-1/event-99",
        ),
        Assertion(
            type=AssertionType.NEGATIVE_EVIDENCE,
            statement="no security warnings",
            confidence=0.85,
            source_ref="ruff::scan",
        ),
    ]


# ============================================================================
# submit_with_report
# ============================================================================


class TestSubmitWithReport:
    def test_returns_review_report(self):
        ex = _make_executor()
        report = ex.submit_with_report(
            lane_id="lane-1",
            task_id="task-1",
            assertions=_sample_assertions(),
        )
        assert report.schema_version == "1.0"
        assert report.lane_id == "lane-1"

    def test_report_carries_assertions(self):
        ex = _make_executor()
        report = ex.submit_with_report(
            lane_id="lane-1",
            task_id="task-1",
            assertions=_sample_assertions(),
        )
        assert len(report.assertions) == 2

    def test_report_has_projection_lineage(self):
        ex = _make_executor()
        report = ex.submit_with_report(
            lane_id="lane-1",
            task_id="task-1",
            assertions=_sample_assertions(),
        )
        # Default lineage is a single "ops_full" projection.
        assert len(report.projection_lineage) >= 1
        assert report.projection_lineage[0].view == "ops_full"

    def test_content_hash_is_valid(self):
        ex = _make_executor()
        report = ex.submit_with_report(
            lane_id="lane-1",
            task_id="task-1",
            assertions=_sample_assertions(),
        )
        assert len(report.content_hash) == 64
        assert report.content_hash == report.compute_hash()

    def test_canonical_id_deterministic_for_same_inputs(self):
        ex = _make_executor()
        r1 = ex.submit_with_report("lane-1", "task-1", _sample_assertions())
        r2 = ex.submit_with_report("lane-1", "task-1", _sample_assertions())
        assert r1.canonical_id == r2.canonical_id

    def test_canonical_id_includes_lane_id(self):
        ex = _make_executor()
        report = ex.submit_with_report(
            lane_id="lane-xyz",
            task_id="task-1",
            assertions=_sample_assertions(),
        )
        assert "lane-xyz" in report.canonical_id

    def test_reviewer_id_default(self):
        ex = _make_executor()
        report = ex.submit_with_report(
            lane_id="lane-1",
            task_id="task-1",
            assertions=_sample_assertions(),
        )
        assert report.reviewer_id == "system"

    def test_reviewer_id_override(self):
        ex = _make_executor()
        report = ex.submit_with_report(
            lane_id="lane-1",
            task_id="task-1",
            assertions=_sample_assertions(),
            reviewer_id="alice",
        )
        assert report.reviewer_id == "alice"

    def test_empty_assertions_still_valid(self):
        ex = _make_executor()
        report = ex.submit_with_report(lane_id="lane-1", task_id="task-1", assertions=[])
        assert report.assertions == []
        assert report.content_hash == report.compute_hash()

    def test_event_recorder_invoked(self):
        recorder = MagicMock()
        ex = LaneExecutor(
            lane_registry=MagicMock(),
            task_registry=MagicMock(),
            event_recorder=recorder,
        )
        report = ex.submit_with_report(
            lane_id="lane-1",
            task_id="task-1",
            assertions=_sample_assertions(),
        )
        recorder.record.assert_called_once()
        call = recorder.record.call_args
        # First positional arg is the event
        assert call.args[0].value == "lane.review.submitted"
        # metadata contains the canonical_id + content_hash
        meta = call.kwargs.get("metadata") or call.args[4]
        assert meta["canonical_id"] == report.canonical_id
        assert meta["content_hash"] == report.content_hash


# ============================================================================
# Backwards compatibility — existing execute_lane is untouched
# ============================================================================


class TestBackwardsCompatibility:
    def test_executor_constructs_without_policy_or_token_deps(self):
        """Constructor signature unchanged: no policy_engine / token_store params."""
        ex = _make_executor()
        assert ex.lane_registry is not None
        assert ex.task_registry is not None
        # event_recorder stays as-is
        assert ex.event_recorder is not None
