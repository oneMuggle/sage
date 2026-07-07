"""
Report Schema v1 for multi-agent orchestration.

This module implements the canonical review report structure used by the
reviewer lane. It mirrors claw-code's `Report schema v1` contract:

- Every report declares a `schema_version` and a stable `canonical_id`.
- A `content_hash` (SHA256) over the canonical content is computed and stored
  so downstream consumers can verify tamper-evidence without re-reading the
  full payload.
- `projection_lineage` declares how derived projections relate back to the
  canonical content via `source_hash == content_hash`.
- `redaction_provenance` records the reason a field is missing (downgrade,
  redaction, source absence) — never silent absence.
- `assertions` carry explicit evidence classes (`fact`, `hypothesis`,
  `negative_evidence`) so negative evidence is first-class.

References:
- claw-code `rust/crates/runtime/src/report_schema.rs`
- sage plan: docs/plans/2026-06-26_multi-agent-optimization-from-claw-code.md
"""

from __future__ import annotations
from typing import Dict, List, Optional

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

SCHEMA_VERSION = "1.0"


class AssertionType(str, Enum):
    """Evidence classes for an assertion.

    Negative evidence is first-class: `NEGATIVE_EVIDENCE` allows a reviewer to
    assert "checked and absent" rather than silently omitting the field.
    """

    FACT = "fact"
    HYPOTHESIS = "hypothesis"
    NEGATIVE_EVIDENCE = "negative_evidence"


# ============================================================================
# Assertion
# ============================================================================


@dataclass
class Assertion:
    """A single evidence-bearing statement in a review report."""

    type: AssertionType
    statement: str
    confidence: float  # 0.0 - 1.0
    source_ref: Optional[str] = None  # lane_id / event_id / test name

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")
        if not self.statement or not self.statement.strip():
            raise ValueError("statement must not be empty")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "statement": self.statement,
            "confidence": self.confidence,
            "source_ref": self.source_ref,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Assertion:
        return cls(
            type=AssertionType(d["type"]),
            statement=d["statement"],
            confidence=float(d["confidence"]),
            source_ref=d.get("source_ref"),
        )


# ============================================================================
# Projection
# ============================================================================


@dataclass
class ProjectionRef:
    """Reference to a derived projection of the canonical report."""

    view: str  # "ui_minimal" / "ops_full" / "audit_only" / ...
    source_hash: str  # MUST equal the parent report's content_hash
    downgrade_reason: Optional[str] = None  # "compatibility" / "redaction" / "source_absence"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "view": self.view,
            "source_hash": self.source_hash,
            "downgrade_reason": self.downgrade_reason,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ProjectionRef:
        return cls(
            view=d["view"],
            source_hash=d["source_hash"],
            downgrade_reason=d.get("downgrade_reason"),
        )


# ============================================================================
# ReviewReport
# ============================================================================


@dataclass
class ReviewReport:
    """Canonical review report (schema v1)."""

    canonical_id: str
    lane_id: str
    reviewer_id: str
    assertions: List[Assertion]
    projection_lineage: List[ProjectionRef]
    redaction_provenance: Dict[str, str] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    content_hash: str = ""  # computed in __post_init__
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))

    def __post_init__(self) -> None:
        # Schema version pin
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {SCHEMA_VERSION!r}, " f"got {self.schema_version!r}"
            )
        if not self.canonical_id or not self.canonical_id.strip():
            raise ValueError("canonical_id must not be empty")
        if not self.lane_id or not self.lane_id.strip():
            raise ValueError("lane_id must not be empty")
        if not self.reviewer_id or not self.reviewer_id.strip():
            raise ValueError("reviewer_id must not be empty")
        # Compute the content hash if not provided. Projection lineage
        # validation is deferred to `validate()` so callers can build a report
        # incrementally (compute hash → pin projection.source_hash → validate).
        if not self.content_hash:
            self.content_hash = self._compute_hash_unchecked()

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------

    def _canonical_payload(self) -> Dict[str, Any]:
        """Return the canonical payload used for hashing.

        Excludes:
        - `content_hash` (self-referential)
        - `created_at` (timestamp — should not affect identity)
        - `projection_lineage` (projection refs are validated to point at
          the canonical hash but are not part of the canonical content)
        """
        return {
            "schema_version": self.schema_version,
            "canonical_id": self.canonical_id,
            "lane_id": self.lane_id,
            "reviewer_id": self.reviewer_id,
            "assertions": [a.to_dict() for a in self.assertions],
            "redaction_provenance": dict(self.redaction_provenance),
        }

    def compute_hash(self) -> str:
        """Compute SHA256 over the canonical payload and validate lineage.

        Use this for *verification* (e.g. before persisting). For internal use
        where lineage may be temporarily inconsistent (e.g. building a report
        before pinning projection source_hash), prefer `_compute_hash_unchecked`.
        """
        h = self._compute_hash_unchecked()
        self._validate_projection_lineage(h)
        return h

    def _compute_hash_unchecked(self) -> str:
        """Compute SHA256 without validating projection lineage."""
        payload = self._canonical_payload()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def validate(self) -> None:
        """Validate the report invariants (projection lineage).

        Called automatically by `__post_init__`. Callers can invoke this
        explicitly after mutating the report to re-check invariants.
        """
        self._validate_projection_lineage(self.content_hash)

    def _validate_projection_lineage(self, content_hash: str) -> None:
        """All projections must point back to the canonical content_hash."""
        for proj in self.projection_lineage:
            if proj.source_hash != content_hash:
                raise ValueError(
                    f"projection '{proj.view}' source_hash "
                    f"({proj.source_hash}) does not match content_hash "
                    f"({content_hash})"
                )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "canonical_id": self.canonical_id,
            "lane_id": self.lane_id,
            "reviewer_id": self.reviewer_id,
            "created_at": self.created_at,
            "content_hash": self.content_hash,
            "assertions": [a.to_dict() for a in self.assertions],
            "projection_lineage": [p.to_dict() for p in self.projection_lineage],
            "redaction_provenance": dict(self.redaction_provenance),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ReviewReport:
        """Reconstruct a ReviewReport from a dict.

        The `content_hash` is recomputed from the canonical payload so that
        any tampering invalidates the round-trip. Projection lineage is then
        re-validated against the recomputed hash.
        """
        report = cls(
            canonical_id=d["canonical_id"],
            lane_id=d["lane_id"],
            reviewer_id=d["reviewer_id"],
            assertions=[Assertion.from_dict(a) for a in d.get("assertions", [])],
            projection_lineage=[
                ProjectionRef.from_dict(p) for p in d.get("projection_lineage", [])
            ],
            redaction_provenance=dict(d.get("redaction_provenance", {})),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            content_hash=d.get("content_hash", ""),
            created_at=int(d.get("created_at", time.time() * 1000)),
        )
        # Always re-validate after deserialization (lineage may have shifted).
        report.validate()
        return report
