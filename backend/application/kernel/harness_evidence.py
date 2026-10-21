# ruff: noqa: UP006, UP007, UP035
"""Harness 提案的证据记录与内容锚定（R85）。"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from backend.application.kernel.harness_files import (
    HarnessFilesError,
    _atomic_write,
    _format_time,
    _prepare_root,
    _safe_target,
)

PROPOSAL_SCHEMA_VERSION = 1
PROPOSAL_KIND = "sage-harness-proposal"
EVIDENCE_KIND = "sage-harness-evidence"
PROBE_KIND = "sage-harness-probe-report"
PROPOSALS_DIR_NAME = "proposals"
EVIDENCE_DIR_NAME = "evidence"
MAX_CANDIDATES = 4
MAX_EDITS_PER_CANDIDATE = 32
MAX_EVIDENCE_EXCERPT_CHARS = 16 * 1024
MAX_EVIDENCE_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_PROBE_BYTES = 1024 * 1024
MAX_PATCH_CHARS = 20000

_ALLOWED_COMPONENTS = frozenset(
    {
        "system",
        "guardrails",
        "memory",
        "tool-guidance",
        "subagents",
        "skills",
        "scripts",
        "plugins",
    }
)
_TRAJECTORY_KINDS = frozenset(
    {"session_event", "message", "tool_trajectory", "llm_replay"}
)
_EVIDENCE_KINDS = _TRAJECTORY_KINDS | {"metric_snapshot", "test_report"}
_STATUSES = frozenset(
    {
        "draft",
        "probed",
        "pending",
        "approved",
        "adopting",
        "adopted",
        "rejected",
        "rolled_back",
        "stale",
        "compose_failed",
    }
)
_LOWER_METRICS = frozenset(
    {
        "tool_error_rate",
        "tool_errors",
        "invalid_loop_count",
        "interruption_rate",
        "correction_rate",
        "duration_ms",
        "static_errors",
    }
)
_HIGHER_METRICS = frozenset({"success_rate", "completion_rate", "task_success_rate"})
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,80}$")
_METRIC_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_REPLAY_FILE_RE = re.compile(r"^rec_[0-9]{4,}\.jsonl$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
__all__ = [
    "EVIDENCE_DIR_NAME",
    "EVIDENCE_KIND",
    "MAX_CANDIDATES",
    "MAX_EDITS_PER_CANDIDATE",
    "MAX_EVIDENCE_BYTES",
    "MAX_EVIDENCE_EXCERPT_CHARS",
    "MAX_MANIFEST_BYTES",
    "MAX_PATCH_CHARS",
    "MAX_PROBE_BYTES",
    "PROBE_KIND",
    "PROPOSALS_DIR_NAME",
    "PROPOSAL_KIND",
    "PROPOSAL_SCHEMA_VERSION",
    "EvidenceRecord",
    "HarnessProposalError",
    "create_harness_evidence",
    "list_harness_evidence",
    "load_harness_evidence",
]

class HarnessProposalError(HarnessFilesError):
    """harness 提案、证据或 Probe 报告非法。"""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_id(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.match(text):
        raise HarnessProposalError("invalid " + label + ": " + repr(value))
    return text


def _new_id(prefix: str) -> str:
    stamp = _format_time(None).replace("-", "").replace(":", "").replace("Z", "")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


def _clean_metrics(raw: Any, *, allow_empty: bool = True) -> Dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise HarnessProposalError("metrics must be an object")
    result: Dict[str, Any] = {}
    for key, value in raw.items():
        name = str(key)
        if not _METRIC_RE.match(name):
            raise HarnessProposalError("invalid metric name: " + repr(key))
        if isinstance(value, bool) or not isinstance(value, (int, float)):  # noqa: UP038 - py38 isinstance 不支持 X | Y
            raise HarnessProposalError("metric must be numeric: " + name)
        if not math.isfinite(float(value)):
            raise HarnessProposalError("metric must be finite: " + name)
        result[name] = value
    if not allow_empty and not result:
        raise HarnessProposalError("metrics must not be empty")
    return result


def _clean_source(kind: str, raw: Any) -> Dict[str, Any]:  # noqa: PLR0911 - 来源逐类校验
    if not isinstance(raw, Mapping):
        raise HarnessProposalError("evidence source must be an object")
    source: Dict[str, Any] = {}
    for key, value in raw.items():
        name = str(key)
        if not _METRIC_RE.match(name):
            raise HarnessProposalError("invalid evidence source field: " + repr(key))
        if not isinstance(value, (str, int)) or isinstance(value, bool):  # noqa: UP038 - py38 isinstance 不支持 X | Y
            raise HarnessProposalError("evidence source values must be strings or integers")
        source[name] = value

    def need_text(field_name: str) -> None:
        if not str(source.get(field_name) or "").strip():
            raise HarnessProposalError(
                f"evidence source requires {field_name}"
            )

    def need_positive_int(field_name: str) -> None:
        value = source.get(field_name)
        if not isinstance(value, int) or value <= 0:
            raise HarnessProposalError(
                f"evidence source requires positive {field_name}"
            )

    if kind == "session_event":
        need_text("session_id")
        need_positive_int("seq")
    elif kind == "message":
        need_text("session_id")
        need_text("message_id")
    elif kind == "tool_trajectory":
        need_text("session_id")
        if not source.get("tool") and not source.get("signature"):
            raise HarnessProposalError("tool trajectory source requires tool or signature")
    elif kind == "llm_replay":
        recording = str(source.get("recording") or "")
        if not _REPLAY_FILE_RE.match(recording):
            raise HarnessProposalError("llm replay source requires rec_NNNN.jsonl")
        need_positive_int("line")
    elif kind == "metric_snapshot":
        need_text("dataset_id")
    elif kind == "test_report":
        if not source.get("report_id") and not source.get("path"):
            raise HarnessProposalError("test report source requires report_id or path")
    return source


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    evidence_kind: str
    source: Dict[str, Any]
    excerpt: str
    excerpt_sha256: str
    metrics: Dict[str, Any]
    created_at: str
    evidence_sha256: str

    def payload(self) -> Dict[str, Any]:
        return {
            "schema_version": PROPOSAL_SCHEMA_VERSION,
            "kind": EVIDENCE_KIND,
            "id": self.evidence_id,
            "evidence_kind": self.evidence_kind,
            "source": dict(self.source),
            "excerpt": self.excerpt,
            "excerpt_sha256": self.excerpt_sha256,
            "metrics": dict(self.metrics),
            "created_at": self.created_at,
        }

    def to_dict(self) -> Dict[str, Any]:
        payload = self.payload()
        payload["evidence_sha256"] = self.evidence_sha256
        return payload


def _parse_evidence_payload(raw: Any, default_created_at: Optional[Any] = None) -> EvidenceRecord:
    if not isinstance(raw, Mapping):
        raise HarnessProposalError("evidence record must be an object")
    kind = str(raw.get("evidence_kind") or raw.get("type") or "").strip()
    if kind not in _EVIDENCE_KINDS:
        raise HarnessProposalError("unsupported evidence kind: " + repr(kind))
    evidence_id = _validate_id(raw.get("id"), "evidence id")
    source = _clean_source(kind, raw.get("source") or {})
    excerpt = str(raw.get("excerpt") or "")
    if len(excerpt) > MAX_EVIDENCE_EXCERPT_CHARS:
        raise HarnessProposalError("evidence excerpt exceeds size limit")
    if kind in _TRAJECTORY_KINDS and not excerpt.strip():
        raise HarnessProposalError("trajectory evidence requires an excerpt")
    metrics = _clean_metrics(raw.get("metrics"))
    if kind == "metric_snapshot" and not metrics:
        raise HarnessProposalError("metric snapshot evidence requires metrics")
    created_at = _format_time(raw.get("created_at") or default_created_at)
    excerpt_sha = _sha256(excerpt.encode("utf-8"))
    if raw.get("excerpt_sha256") not in (None, excerpt_sha):
        raise HarnessProposalError("evidence excerpt hash mismatch: " + evidence_id)
    payload = {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "kind": EVIDENCE_KIND,
        "id": evidence_id,
        "evidence_kind": kind,
        "source": source,
        "excerpt": excerpt,
        "excerpt_sha256": excerpt_sha,
        "metrics": metrics,
        "created_at": created_at,
    }
    evidence_sha = _sha256(_canonical_json(payload))
    if raw.get("evidence_sha256") not in (None, evidence_sha):
        raise HarnessProposalError("evidence hash mismatch: " + evidence_id)
    if raw.get("schema_version") not in (None, PROPOSAL_SCHEMA_VERSION):
        raise HarnessProposalError("unsupported evidence schema_version")
    if raw.get("kind") not in (None, EVIDENCE_KIND):
        raise HarnessProposalError("unexpected evidence kind")
    return EvidenceRecord(
        evidence_id, kind, source, excerpt, excerpt_sha, metrics, created_at, evidence_sha
    )


def _evidence_path(root: Path, evidence_id: str) -> Path:
    return _safe_target(root, f"{EVIDENCE_DIR_NAME}/{evidence_id}.json")


def _write_evidence_record(root: Path, record: EvidenceRecord) -> None:
    payload = json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n"
    data = payload.encode("utf-8")
    if len(data) > MAX_EVIDENCE_BYTES:
        raise HarnessProposalError("evidence record exceeds size limit")
    _atomic_write(root, f"{EVIDENCE_DIR_NAME}/{record.evidence_id}.json", data)


def create_harness_evidence(
    root: Any,
    evidence_id: str,
    evidence_kind: str,
    source: Mapping[str, Any],
    *,
    excerpt: str = "",
    metrics: Optional[Mapping[str, Any]] = None,
    created_at: Optional[Any] = None,
    overwrite: bool = False,
) -> EvidenceRecord:
    """创建一份带内容哈希的 evidence 记录。"""
    path = _prepare_root(root, create=True)
    record = _parse_evidence_payload(
        {
            "id": evidence_id,
            "evidence_kind": evidence_kind,
            "source": dict(source),
            "excerpt": excerpt,
            "metrics": dict(metrics or {}),
            "created_at": created_at,
        },
        created_at,
    )
    target = _evidence_path(path, record.evidence_id)
    if target.exists() and not overwrite:
        raise HarnessProposalError("evidence already exists: " + record.evidence_id)
    _write_evidence_record(path, record)
    return record


def load_harness_evidence(root: Any, evidence_id: str) -> EvidenceRecord:
    """加载并校验一份 evidence 记录。"""
    path = _prepare_root(root)
    selected = _validate_id(evidence_id, "evidence id")
    target = _evidence_path(path, selected)
    if target.is_symlink() or not target.is_file():
        raise HarnessProposalError("evidence not found: " + selected)
    if target.stat().st_size > MAX_EVIDENCE_BYTES:
        raise HarnessProposalError("evidence record exceeds size limit")
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise HarnessProposalError(f"invalid evidence record: {exc}") from exc
    record = _parse_evidence_payload(raw)
    if record.evidence_id != selected:
        raise HarnessProposalError("evidence id mismatch: " + selected)
    return record


def list_harness_evidence(root: Any) -> List[EvidenceRecord]:
    path = _prepare_root(root)
    directory = path / EVIDENCE_DIR_NAME
    if not directory.exists():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise HarnessProposalError("evidence directory is invalid")
    result: List[EvidenceRecord] = []
    for child in sorted(directory.iterdir(), key=lambda item: item.name):
        if child.suffix != ".json" or child.is_symlink() or not child.is_file():
            continue
        try:
            result.append(load_harness_evidence(path, child.stem))
        except HarnessFilesError:
            continue
    return result
