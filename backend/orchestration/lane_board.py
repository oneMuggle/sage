"""
Lane Board snapshot + freshness + capability negotiation.

Implements claw-code's `LaneBoard` + `LaneFreshness` + capability-negotiation
patterns:

- `LaneBoardSnapshot` groups lanes into active / blocked / finished and
  attaches per-lane freshness so the UI can decide whether the board is
  trustworthy.
- `LaneFreshness` derives a level (`fresh` / `stale` / `dead`) from the age
  of the most recent heartbeat — never from terminal text.
- `CapabilityManifest` declares what views / schema versions / field
  families the producer supports.
- `ProjectionRequest` + `BoardProjection` perform a typed negotiation:
  the producer returns a projection that explicitly lists every omitted
  field (`redaction_provenance`) and every version downgrade
  (`downgrade_for_compatibility`).

This module is the M4 deliverable: `board.json` freshness + UI-facing
projection selection.

References:
- claw-code `rust/crates/runtime/src/task_registry.rs` (LaneBoard, freshness)
- claw-code `docs/g004-events-reports-contract.md` (capability negotiation)
- sage plan: docs/plans/2026-06-26_multi-agent-optimization-from-claw-code.md
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

# ============================================================================
# Errors
# ============================================================================


class UnsupportedViewError(Exception):  # noqa: N818 — short domain name
    """Raised when a projection request names a view the producer doesn't support."""


# ============================================================================
# Freshness
# ============================================================================


# Thresholds (milliseconds). Chosen to match `heartbeat.py` defaults:
#   stalled_after = 300s, dead_after = 600s.
FRESH_THRESHOLD_MS = 30_000  # < 30s = fresh
STALE_THRESHOLD_MS = 300_000  # 30s..300s = stale; ≥300s = dead


_FreshnessLevel = Literal["fresh", "stale", "dead"]


@dataclass
class LaneFreshness:
    """Per-lane freshness derived from heartbeat timestamps.

    `last_heartbeat_at` is the producer-side timestamp (ms unix) of the
    most recent heartbeat. When `None`, the lane is treated as dead
    ("no_heartbeat_observed" reason).
    """

    lane_id: str
    last_heartbeat_at: Optional[int]
    age_ms: Optional[int]
    level: _FreshnessLevel
    reasons: List[str] = field(default_factory=list)

    @classmethod
    def from_age(
        cls,
        lane_id: str,
        age_ms: Optional[int],
        last_heartbeat_at: Optional[int] = None,
        now_ms: Optional[int] = None,  # noqa: ARG003 — kept for API symmetry
    ) -> LaneFreshness:
        """Compute freshness from an explicit age in ms (or None = no heartbeat)."""
        if age_ms is None:
            return cls(
                lane_id=lane_id,
                last_heartbeat_at=last_heartbeat_at,
                age_ms=None,
                level="dead",
                reasons=["no_heartbeat_observed"],
            )
        if age_ms >= STALE_THRESHOLD_MS:
            return cls(
                lane_id=lane_id,
                last_heartbeat_at=last_heartbeat_at,
                age_ms=age_ms,
                level="dead",
                reasons=["age_exceeds_stale_threshold"],
            )
        if age_ms >= FRESH_THRESHOLD_MS:
            return cls(
                lane_id=lane_id,
                last_heartbeat_at=last_heartbeat_at,
                age_ms=age_ms,
                level="stale",
                reasons=["age_exceeds_fresh_threshold"],
            )
        return cls(
            lane_id=lane_id,
            last_heartbeat_at=last_heartbeat_at,
            age_ms=age_ms,
            level="fresh",
            reasons=[],
        )

    @classmethod
    def from_heartbeat(
        cls,
        lane_id: str,
        last_heartbeat_at: Optional[int],
        now_ms: Optional[int] = None,
    ) -> LaneFreshness:
        """Compute freshness from a heartbeat timestamp."""
        if last_heartbeat_at is None:
            return cls.from_age(lane_id=lane_id, age_ms=None, last_heartbeat_at=None)
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        age = max(0, now - last_heartbeat_at)
        return cls.from_age(lane_id=lane_id, age_ms=age, last_heartbeat_at=last_heartbeat_at)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lane_id": self.lane_id,
            "last_heartbeat_at": self.last_heartbeat_at,
            "age_ms": self.age_ms,
            "level": self.level,
            "reasons": list(self.reasons),
        }


@dataclass
class FreshnessSummary:
    """Aggregate freshness counts + overall level (worst-of-three)."""

    total: int
    fresh: int
    stale: int
    dead: int
    overall_level: _FreshnessLevel

    @classmethod
    def from_entries(cls, entries: List[LaneFreshness]) -> FreshnessSummary:
        fresh = sum(1 for e in entries if e.level == "fresh")
        stale = sum(1 for e in entries if e.level == "stale")
        dead = sum(1 for e in entries if e.level == "dead")
        if dead > 0:
            overall: _FreshnessLevel = "dead"
        elif stale > 0:
            overall = "stale"
        else:
            overall = "fresh"
        return cls(
            total=len(entries),
            fresh=fresh,
            stale=stale,
            dead=dead,
            overall_level=overall,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "fresh": self.fresh,
            "stale": self.stale,
            "dead": self.dead,
            "overall_level": self.overall_level,
        }


# ============================================================================
# Board entries + snapshot
# ============================================================================


@dataclass
class BoardEntry:
    """One lane rendered for the board."""

    lane_id: str
    task_id: str
    agent_id: Optional[str]
    status: str
    freshness: LaneFreshness
    last_event_at: int
    last_event_type: str
    heartbeat_status: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lane_id": self.lane_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "freshness": self.freshness.to_dict(),
            "last_event_at": self.last_event_at,
            "last_event_type": self.last_event_type,
            "heartbeat_status": self.heartbeat_status,
        }


_SCHEMA_VERSION = "1.0"


@dataclass
class LaneBoardSnapshot:
    """A point-in-time view of all lanes grouped by status, with freshness."""

    schema_version: str
    generated_at: int
    generated_by: str
    active: List[BoardEntry]
    blocked: List[BoardEntry]
    finished: List[BoardEntry]
    freshness_summary: FreshnessSummary

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "generated_by": self.generated_by,
            "active": [e.to_dict() for e in self.active],
            "blocked": [e.to_dict() for e in self.blocked],
            "finished": [e.to_dict() for e in self.finished],
            "freshness_summary": self.freshness_summary.to_dict(),
        }

    def content_hash(self) -> str:
        """Deterministic SHA256 of the snapshot body for content addressing."""
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Capability negotiation
    # ------------------------------------------------------------------

    def project(self, request: ProjectionRequest) -> BoardProjection:
        """Project this snapshot according to a consumer's `ProjectionRequest`."""
        manifest = CapabilityManifest.default_for_board_v1()
        if request.requested_view not in manifest.projection_views:
            raise UnsupportedViewError(
                f"requested_view={request.requested_view!r} not in " f"{manifest.projection_views}"
            )

        downgrade: List[str] = []
        if request.max_schema_version and _is_version_older(
            request.max_schema_version, self.schema_version
        ):
            downgrade.append(
                f"schema_version_downgrade:{self.schema_version}->{request.max_schema_version}"
            )

        all_entries = self.active + self.blocked + self.finished
        redaction_provenance: Dict[str, str] = {}
        projected_entries: List[Dict[str, Any]] = []

        # Define field families a consumer can request.
        # "lifecycle" → core lane fields
        # "branch_health" → freshness + heartbeat_status
        # "ship" → last_event_at + last_event_type
        FIELDS_BY_FAMILY: Dict[str, Set[str]] = {
            "lifecycle": {"lane_id", "task_id", "agent_id", "status"},
            "branch_health": {"freshness", "heartbeat_status"},
            "ship": {"last_event_at", "last_event_type"},
        }

        # ui_minimal: lifecycle only. ops_full: all fields. Default: lifecycle + ship.
        if request.requested_view == "ui_minimal":
            allowed_families = {"lifecycle"}
        elif request.requested_view == "ops_full":
            allowed_families = {"lifecycle", "branch_health", "ship"}
        else:
            allowed_families = set(request.accepted_field_families) or {"lifecycle"}

        allowed_fields: Set[str] = set()
        for fam in allowed_families:
            allowed_fields |= FIELDS_BY_FAMILY.get(fam, set())

        for entry in all_entries:
            full = entry.to_dict()
            projected: Dict[str, Any] = {}
            for k, v in full.items():
                if k == "lane_id":
                    # lane_id is always preserved (cross-reference invariant).
                    projected[k] = v
                elif k in allowed_fields:
                    projected[k] = v
                else:
                    redaction_provenance[k] = (
                        f"field not in accepted_field_families={sorted(allowed_families)}"
                    )
            projected_entries.append(projected)

        return BoardProjection(
            parent_content_hash=self.content_hash(),
            parent_schema_version=self.schema_version,
            view=request.requested_view,
            entries=projected_entries,
            downgrade_for_compatibility=downgrade,
            redaction_provenance=redaction_provenance,
        )


def _parse_version(version: str) -> Tuple[int, ...]:
    """Parse a version string like "board@1.0" or "1.0" into a numeric tuple."""
    # Strip "<prefix>@" prefix if present.
    body = version.split("@", 1)[-1]
    parts: List[int] = []
    for chunk in body.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            # Non-numeric chunk — treat as 0 so comparison stays sane.
            parts.append(0)
    return tuple(parts)


def _is_version_older(candidate: str, reference: str) -> bool:
    """Return True if `candidate` is strictly older than `reference`.

    Comparison is on the numeric tuple (major, minor, ...). Non-numeric
    parts default to 0.
    """
    return _parse_version(candidate) < _parse_version(reference)


# ============================================================================
# Builder
# ============================================================================


_ACTIVE_STATUSES = {"running", "queued", "ready", "started"}
_BLOCKED_STATUSES = {"blocked"}
_FINISHED_STATUSES = {"succeeded", "failed", "stopped", "cancelled", "merged"}


class LaneBoardBuilder:
    """Build `LaneBoardSnapshot` from a `LaneRegistry`.

    Reads:
    - `lane.lane_id`, `lane.task_id`, `lane.agent_id`
    - `lane.status` (enum with `.value`)
    - `lane.heartbeat.last_heartbeat_at` (optional)
    """

    def __init__(self, lane_registry: Any) -> None:
        self.lane_registry = lane_registry

    def freshness_for(self, lane: Any, now_ms: Optional[int] = None) -> LaneFreshness:
        last_hb: Optional[int] = None
        if getattr(lane, "heartbeat", None) is not None:
            last_hb = getattr(lane.heartbeat, "last_heartbeat_at", None)
        return LaneFreshness.from_heartbeat(
            lane_id=lane.lane_id, last_heartbeat_at=last_hb, now_ms=now_ms
        )

    def build_snapshot(self, actor: str, now_ms: Optional[int] = None) -> LaneBoardSnapshot:
        lanes = self.lane_registry.list_all_lanes()
        now = now_ms if now_ms is not None else int(time.time() * 1000)

        active: List[BoardEntry] = []
        blocked: List[BoardEntry] = []
        finished: List[BoardEntry] = []

        all_freshness: List[LaneFreshness] = []

        for lane in lanes:
            status_value = lane.status.value if hasattr(lane.status, "value") else str(lane.status)
            freshness = self.freshness_for(lane, now_ms=now)
            all_freshness.append(freshness)
            entry = BoardEntry(
                lane_id=lane.lane_id,
                task_id=lane.task_id,
                agent_id=lane.agent_id,
                status=status_value,
                freshness=freshness,
                last_event_at=now,
                last_event_type="board.snapshot",
                heartbeat_status=freshness.level,
            )
            if status_value in _ACTIVE_STATUSES:
                active.append(entry)
            elif status_value in _BLOCKED_STATUSES:
                blocked.append(entry)
            elif status_value in _FINISHED_STATUSES:
                finished.append(entry)
            else:
                # Unknown status — fall back to active (visible to UI).
                active.append(entry)

        summary = FreshnessSummary.from_entries(all_freshness)

        return LaneBoardSnapshot(
            schema_version=_SCHEMA_VERSION,
            generated_at=now,
            generated_by=actor,
            active=active,
            blocked=blocked,
            finished=finished,
            freshness_summary=summary,
        )


# ============================================================================
# Capability negotiation
# ============================================================================


@dataclass
class CapabilityManifest:
    """Producer-side declaration of supported views / schema versions / families."""

    emitter: str
    schema_versions: List[str]
    field_families: List[str]
    projection_views: List[str]
    redaction_policy: str
    fixture_suite_version: str = "1.0"

    @classmethod
    def default_for_board_v1(cls) -> CapabilityManifest:
        return cls(
            emitter="backend.orchestration.lane_board",
            schema_versions=["board@1.0"],
            field_families=["lifecycle", "branch_health", "ship"],
            projection_views=["ui_minimal", "ops_full"],
            redaction_policy="field_redaction_with_provenance",
            fixture_suite_version="1.0",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "emitter": self.emitter,
            "schema_versions": list(self.schema_versions),
            "field_families": list(self.field_families),
            "projection_views": list(self.projection_views),
            "redaction_policy": self.redaction_policy,
            "fixture_suite_version": self.fixture_suite_version,
        }


@dataclass
class ProjectionRequest:
    """Consumer-side request: which view / which families / max schema."""

    consumer: str
    requested_view: str
    accepted_field_families: List[str] = field(default_factory=list)
    max_schema_version: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "consumer": self.consumer,
            "requested_view": self.requested_view,
            "accepted_field_families": list(self.accepted_field_families),
            "max_schema_version": self.max_schema_version,
        }


@dataclass
class BoardProjection:
    """Result of capability negotiation: projected entries + provenance metadata."""

    parent_content_hash: str
    parent_schema_version: str
    view: str
    entries: List[Dict[str, Any]]
    downgrade_for_compatibility: List[str] = field(default_factory=list)
    redaction_provenance: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parent_content_hash": self.parent_content_hash,
            "parent_schema_version": self.parent_schema_version,
            "view": self.view,
            "entries": list(self.entries),
            "downgrade_for_compatibility": list(self.downgrade_for_compatibility),
            "redaction_provenance": dict(self.redaction_provenance),
        }
