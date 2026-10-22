# ruff: noqa: UP006, UP007, UP035
"""HarnessProposal 的 Probe、Compose 与采纳状态机（R85）。"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from backend.application.kernel.harness_evidence import (
    _HIGHER_METRICS,
    _LOWER_METRICS,
    _TRAJECTORY_KINDS,
    MAX_PROBE_BYTES,
    PROBE_KIND,
    PROPOSAL_SCHEMA_VERSION,
    HarnessProposalError,
    _canonical_json,
    _clean_metrics,
    _sha256,
    _validate_id,
    load_harness_evidence,
)
from backend.application.kernel.harness_files import (
    HarnessFileEntry,
    HarnessFilesError,
    HarnessFileSpec,
    _atomic_write,
    _build_lock,
    _delete_file,
    _entries_from_files,
    _format_time,
    _prepare_root,
    _raise_for_issues,
    _safe_target,
    _scan_files,
    _validate_managed_path,
    _write_lock,
    infer_harness_component,
    verify_harness_files,
    write_harness_file_specs,
)
from backend.application.kernel.harness_proposals import (
    HarnessProposal,
    ProposalCandidate,
    ProposalEdit,
    _proposal_dir,
    _read_artifact,
    _record_event,
    _save_proposal,
    load_harness_proposal,
)
from backend.application.kernel.harness_snapshots import (
    create_harness_snapshot,
    rollback_harness_files,
)

__all__ = [
    "adopt_harness_proposal",
    "approve_harness_proposal",
    "compose_harness_proposal",
    "mark_harness_proposal_submitted",
    "record_harness_probe",
    "reject_harness_proposal",
    "rollback_harness_proposal",
    "stage_harness_candidate",
]

def _metric_direction(name: str) -> Optional[str]:
    if name in _HIGHER_METRICS:
        return "higher"
    if name in _LOWER_METRICS or name.endswith("_tokens"):
        return "lower"
    return None


def _validate_probe_metrics(raw: Any) -> Dict[str, Any]:
    metrics = _clean_metrics(raw, allow_empty=False)
    for name, value in metrics.items():
        if _metric_direction(name) is not None and float(value) < 0:
            raise HarnessProposalError("behavior metric must be nonnegative: " + name)
        if name.endswith("_rate") and not 0 <= float(value) <= 1:
            raise HarnessProposalError("rate metric must be between 0 and 1: " + name)
    return metrics


def _candidate_score(
    base: Mapping[str, Any], candidate: Mapping[str, Any]
) -> Tuple[bool, float, List[str], List[str]]:
    reasons: List[str] = []
    improvements: List[float] = []
    common: List[str] = []
    for name in sorted(set(base) & set(candidate)):
        direction = _metric_direction(name)
        if direction is None:
            continue
        common.append(name)
        base_value = float(base[name])
        value = float(candidate[name])
        if direction == "lower":
            if value > base_value + 1e-12:
                reasons.append("metric_regression:" + name)
            improvement = 0.0 if base_value == 0 else (base_value - value) / abs(base_value)
        else:
            if value < base_value - 1e-12:
                reasons.append("metric_regression:" + name)
            improvement = 0.0 if base_value == 0 else (value - base_value) / abs(base_value)
        improvements.append(max(-1.0, min(1.0, improvement)))
    behavioral = [name for name in common if name != "static_errors"]
    if not behavioral:
        reasons.append("no_common_behavior_metric")
    score = sum(improvements) / len(improvements) if improvements else 0.0
    return not reasons, score, reasons, common


def record_harness_probe(
    root: Any,
    proposal_id: str,
    report: Mapping[str, Any],
    *,
    recorded_at: Optional[Any] = None,
    actor: str = "local",
) -> HarnessProposal:
    """校验并记录一份离线 Probe 报告。"""
    path = _prepare_root(root)
    proposal = load_harness_proposal(path, proposal_id)
    if proposal.status not in ("draft", "probed"):
        raise HarnessProposalError("probe requires a draft proposal")
    if report.get("schema_version") not in (None, PROPOSAL_SCHEMA_VERSION):
        raise HarnessProposalError("unsupported probe schema_version")
    if report.get("kind") not in (None, PROBE_KIND):
        raise HarnessProposalError("unexpected probe kind")
    dataset = report.get("dataset")
    if not isinstance(dataset, Mapping) or not str(dataset.get("id") or "").strip():
        raise HarnessProposalError("probe dataset id is required")
    dataset_ids_raw = dataset.get("evidence_ids")
    if not isinstance(dataset_ids_raw, list) or not dataset_ids_raw:
        raise HarnessProposalError("probe dataset requires evidence")
    dataset_ids = [_validate_id(item, "evidence id") for item in dataset_ids_raw]
    dataset_records = [load_harness_evidence(path, item) for item in dataset_ids]
    if not any(item.evidence_kind in _TRAJECTORY_KINDS for item in dataset_records):
        raise HarnessProposalError("probe dataset requires trajectory evidence")
    base_metrics = _validate_probe_metrics(report.get("base_metrics"))
    if not any(
        _metric_direction(name) is not None and name != "static_errors"
        for name in base_metrics
    ):
        raise HarnessProposalError("probe requires a base behavior metric")
    candidates_raw = report.get("candidates")
    if not isinstance(candidates_raw, Mapping) or not candidates_raw:
        raise HarnessProposalError("probe requires candidate results")
    proposal_candidates = {item.candidate_id: item for item in proposal.candidates}
    normalized_candidates: Dict[str, Any] = {}
    for candidate_id, raw_candidate in candidates_raw.items():
        selected = _validate_id(candidate_id, "candidate id")
        candidate = proposal_candidates.get(selected)
        if candidate is None or not isinstance(raw_candidate, Mapping):
            raise HarnessProposalError("unknown probe candidate: " + str(candidate_id))
        metrics = _validate_probe_metrics(raw_candidate.get("metrics"))
        raw_edits = raw_candidate.get("edits") or {}
        if not isinstance(raw_edits, Mapping):
            raise HarnessProposalError("probe candidate edits must be an object")
        candidate_paths = {edit.path: edit for edit in candidate.edits}
        normalized_edits: Dict[str, Any] = {}
        for edit_path, raw_edit in raw_edits.items():
            normalized_path = _validate_managed_path(str(edit_path))
            edit = candidate_paths.get(normalized_path)
            if edit is None or not isinstance(raw_edit, Mapping):
                raise HarnessProposalError("unknown probe edit: " + str(edit_path))
            supported = raw_edit.get("supported")
            if not isinstance(supported, bool):
                raise HarnessProposalError("probe edit supported must be boolean")
            raw_ids = raw_edit.get("evidence_ids") or []
            if not isinstance(raw_ids, list):
                raise HarnessProposalError("probe edit evidence_ids must be a list")
            evidence_ids = [_validate_id(item, "evidence id") for item in raw_ids]
            allowed = set(edit.evidence_ids) | set(dataset_ids)
            if not set(evidence_ids) <= allowed:
                raise HarnessProposalError("probe edit cites unanchored evidence")
            for item in evidence_ids:
                load_harness_evidence(path, item)
            normalized_edits[normalized_path] = {
                "supported": supported,
                "evidence_ids": evidence_ids,
                "notes": str(raw_edit.get("notes") or ""),
            }
        normalized_candidates[selected] = {
            "metrics": metrics,
            "edits": normalized_edits,
        }
    normalized = {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "kind": PROBE_KIND,
        "dataset": {
            "id": str(dataset.get("id")),
            "description": str(dataset.get("description") or ""),
            "evidence_ids": dataset_ids,
        },
        "base_metrics": base_metrics,
        "candidates": normalized_candidates,
    }
    probe_sha = _sha256(_canonical_json(normalized))
    proposal_dir = _proposal_dir(path, proposal.proposal_id)
    payload = (json.dumps(normalized, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(payload) > MAX_PROBE_BYTES:
        raise HarnessProposalError("probe report exceeds size limit")
    _atomic_write(proposal_dir, "probe.json", payload)
    proposal.probe = {
        "report": normalized,
        "probe_sha256": probe_sha,
        "recorded_at": _format_time(recorded_at),
    }
    proposal.selected_edits = ()
    proposal.compose = {}
    proposal.status = "probed"
    _record_event(
        proposal,
        "probed",
        actor=actor,
        at=recorded_at,
        details={"dataset_id": normalized["dataset"]["id"]},
    )
    _save_proposal(path, proposal)
    return proposal


def compose_harness_proposal(
    root: Any,
    proposal_id: str,
    *,
    composed_at: Optional[Any] = None,
    actor: str = "local",
) -> HarnessProposal:
    """按 Probe 证据与指标确定性筛选候选编辑。"""
    path = _prepare_root(root)
    proposal = load_harness_proposal(path, proposal_id)
    if proposal.status != "probed" or not proposal.probe:
        raise HarnessProposalError("compose requires a probed proposal")
    report = proposal.probe.get("report")
    if not isinstance(report, Mapping):
        raise HarnessProposalError("probe report is missing")
    base_metrics = _validate_probe_metrics(report.get("base_metrics"))
    report_candidates = report.get("candidates") or {}
    scores: Dict[str, Dict[str, Any]] = {}
    discarded: List[Dict[str, Any]] = []
    grouped: Dict[str, List[Tuple[ProposalCandidate, ProposalEdit, float]]] = {}
    for candidate in proposal.candidates:
        candidate_report = report_candidates.get(candidate.candidate_id)
        if not isinstance(candidate_report, Mapping):
            scores[candidate.candidate_id] = {
                "eligible": False,
                "score": 0.0,
                "reasons": ["missing_probe_result"],
                "metrics": [],
            }
            for edit in candidate.edits:
                discarded.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "path": edit.path,
                        "reason": "missing_probe_result",
                    }
                )
            continue
        eligible, score, reasons, common = _candidate_score(
            base_metrics, _validate_probe_metrics(candidate_report.get("metrics"))
        )
        scores[candidate.candidate_id] = {
            "eligible": eligible,
            "score": score,
            "reasons": reasons,
            "metrics": common,
        }
        edit_reports = candidate_report.get("edits") or {}
        for edit in candidate.edits:
            if not eligible:
                discarded.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "path": edit.path,
                        "reason": "candidate_ineligible",
                    }
                )
                continue
            edit_report = edit_reports.get(edit.path) if isinstance(edit_reports, Mapping) else None
            if not isinstance(edit_report, Mapping) or edit_report.get("supported") is not True:
                discarded.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "path": edit.path,
                        "reason": "unsupported_edit",
                    }
                )
                continue
            records = [load_harness_evidence(path, item) for item in edit.evidence_ids]
            if not any(item.evidence_kind in _TRAJECTORY_KINDS for item in records):
                discarded.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "path": edit.path,
                        "reason": "missing_trajectory_evidence",
                    }
                )
                continue
            grouped.setdefault(edit.path, []).append((candidate, edit, score))

    selected: List[ProposalEdit] = []
    proposal_dir = _proposal_dir(path, proposal.proposal_id)
    composed_data: Dict[str, bytes] = {}
    for edit_path in sorted(grouped):
        entries = grouped[edit_path]
        by_result: Dict[Tuple[str, Optional[str]], List[Tuple[ProposalCandidate, ProposalEdit, float]]] = {}
        for item in entries:
            by_result.setdefault((item[1].operation, item[1].after_sha256), []).append(item)
        ranked = sorted(
            by_result.items(),
            key=lambda item: max(entry[2] for entry in item[1]),
            reverse=True,
        )
        if len(ranked) > 1 and abs(
            max(entry[2] for entry in ranked[0][1])
            - max(entry[2] for entry in ranked[1][1])
        ) <= 1e-12:
            for candidate, _edit, _score in entries:
                discarded.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "path": edit_path,
                        "reason": "conflict_tie",
                    }
                )
            continue
        winning_key, winning_entries = ranked[0]
        for _result_key, result_entries in ranked[1:]:
            for candidate, _edit, _score in result_entries:
                discarded.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "path": edit_path,
                        "reason": "conflict_lost",
                    }
                )
        winner = max(winning_entries, key=lambda item: item[2])
        evidence_union: List[str] = []
        for _candidate, edit, _score in winning_entries:
            for evidence_id in edit.evidence_ids:
                if evidence_id not in evidence_union:
                    evidence_union.append(evidence_id)
        winning_edit = winner[1]
        selected.append(
            ProposalEdit(
                path=edit_path,
                operation=winning_edit.operation,
                base_sha256=winning_edit.base_sha256,
                after_sha256=winning_edit.after_sha256,
                size=winning_edit.size,
                evidence_ids=tuple(evidence_union),
                rationale=winning_edit.rationale,
                candidate_id=winner[0].candidate_id,
            )
        )
        if winning_edit.operation == "write":
            composed_data[edit_path] = _read_artifact(
                proposal_dir,
                f"candidates/{winner[0].candidate_id}/files/{edit_path}",
                winning_edit.after_sha256,
                "candidate file",
            )

    proposal.compose = {
        "composed_at": _format_time(composed_at),
        "candidate_scores": scores,
        "selected_paths": [item.path for item in selected],
        "discarded": discarded,
    }
    if not selected:
        proposal.status = "compose_failed"
        _record_event(proposal, "compose_failed", actor=actor, at=composed_at)
        _save_proposal(path, proposal)
        raise HarnessProposalError("no evidence-supported edits survived compose")

    composed_dir = proposal_dir / "composed"
    if composed_dir.exists() or composed_dir.is_symlink():
        raise HarnessProposalError("composed artifacts already exist")
    staging = proposal_dir / f".composed-staging-{uuid.uuid4().hex[:8]}"
    try:
        staging.mkdir(parents=False, exist_ok=False)
        (staging / "files").mkdir(parents=True, exist_ok=False)
        files_root = staging / "files"
        for edit_path, data in sorted(composed_data.items()):
            _atomic_write(files_root, edit_path, data)
        staging.replace(composed_dir)
    except BaseException:
        if staging.exists():
            shutil.rmtree(str(staging), ignore_errors=True)
        raise
    proposal.selected_edits = tuple(selected)
    proposal.status = "pending"
    _record_event(
        proposal,
        "composed",
        actor=actor,
        at=composed_at,
        details={"selected_files": len(selected)},
    )
    _save_proposal(path, proposal)
    return proposal
def stage_harness_candidate(
    root: Any, proposal_id: str, candidate_id: str, destination: Any
) -> Dict[str, Any]:
    """把某个 candidate 物化到一个空的临时 harness 根（静态 Probe 用）。"""
    path = _prepare_root(root)
    proposal = load_harness_proposal(path, proposal_id)
    candidate = next(
        (item for item in proposal.candidates if item.candidate_id == candidate_id), None
    )
    if candidate is None:
        raise HarnessProposalError("unknown candidate: " + str(candidate_id))
    verification = verify_harness_files(path)
    if not verification.valid or verification.lock is None:
        _raise_for_issues(verification.issues)
        raise HarnessProposalError("candidate staging requires a valid harness lock")
    if verification.lock.content_sha256 != proposal.base_lock_content_sha256:
        raise HarnessProposalError("proposal base lock is stale")
    specs: Dict[str, HarnessFileSpec] = {}
    entries = {item.path: item for item in verification.current_files}
    for edit_path, entry in entries.items():
        specs[edit_path] = HarnessFileSpec(
            path=edit_path,
            content=_safe_target(path, edit_path).read_bytes(),
            component=entry.component,
            provenance=entry.provenance,
            owner=entry.owner,
            authority=entry.authority,
        )
    proposal_dir = _proposal_dir(path, proposal.proposal_id)
    for edit in candidate.edits:
        if edit.operation == "delete":
            specs.pop(edit.path, None)
            continue
        old = entries.get(edit.path)
        specs[edit.path] = HarnessFileSpec(
            path=edit.path,
            content=_read_artifact(
                proposal_dir,
                f"candidates/{candidate.candidate_id}/files/{edit.path}",
                edit.after_sha256,
                "candidate file",
            ),
            component=old.component if old else infer_harness_component(edit.path),
            provenance=f"harness-proposal:{proposal.proposal_id}:{candidate.candidate_id}",
            owner=proposal.author,
            authority=old.authority if old else "configuration" if edit.path == "plugins.yaml" else "projection",
        )
    staged_path, spec_map, lock = write_harness_file_specs(
        destination,
        [specs[key] for key in sorted(specs)],
        generator="harness proposal static probe",
        startup_enforced=verification.lock.startup_enforced,
    )
    return {
        "root": str(staged_path),
        "candidate_id": candidate.candidate_id,
        "file_count": len(spec_map),
        "lock": lock.to_dict(),
    }


def _require_base_current(
    root: Path, proposal: HarnessProposal, *, mark_stale: bool = False
) -> Any:
    verification = verify_harness_files(root)
    current = bool(
        verification.valid
        and verification.lock is not None
        and verification.lock.content_sha256 == proposal.base_lock_content_sha256
    )
    if current:
        return verification
    if mark_stale and proposal.status in ("pending", "approved"):
        proposal.status = "stale"
        _record_event(proposal, "stale")
        _save_proposal(root, proposal)
    _raise_for_issues(verification.issues)
    raise HarnessProposalError("proposal base lock is stale")


def _validate_selected_evidence(root: Path, proposal: HarnessProposal) -> None:
    if not proposal.selected_edits:
        raise HarnessProposalError("proposal has no composed edits")
    for edit in proposal.selected_edits:
        records = [load_harness_evidence(root, item) for item in edit.evidence_ids]
        if not any(item.evidence_kind in _TRAJECTORY_KINDS for item in records):
            raise HarnessProposalError(
                "selected edit requires trajectory evidence: " + edit.path
            )


def approve_harness_proposal(
    root: Any,
    proposal_id: str,
    *,
    actor: str = "local",
    approved_at: Optional[Any] = None,
) -> HarnessProposal:
    path = _prepare_root(root)
    proposal = load_harness_proposal(path, proposal_id)
    if proposal.status != "pending":
        raise HarnessProposalError("approve requires a pending proposal")
    _require_base_current(path, proposal, mark_stale=True)
    _validate_selected_evidence(path, proposal)
    proposal.status = "approved"
    proposal.review.update(
        {"decision": "approved", "decided_by": str(actor), "decided_at": _format_time(approved_at)}
    )
    _record_event(proposal, "approved", actor=actor, at=approved_at)
    _save_proposal(path, proposal)
    return proposal


def reject_harness_proposal(
    root: Any,
    proposal_id: str,
    *,
    actor: str = "local",
    reason: str = "",
    rejected_at: Optional[Any] = None,
) -> HarnessProposal:
    path = _prepare_root(root)
    proposal = load_harness_proposal(path, proposal_id)
    if proposal.status not in ("draft", "probed", "pending", "approved", "compose_failed"):
        raise HarnessProposalError("proposal cannot be rejected from status " + proposal.status)
    proposal.status = "rejected"
    proposal.review.update(
        {
            "decision": "rejected",
            "decided_by": str(actor),
            "decided_at": _format_time(rejected_at),
            "reason": str(reason or ""),
        }
    )
    _record_event(
        proposal,
        "rejected",
        actor=actor,
        at=rejected_at,
        details={"reason": str(reason or "")},
    )
    _save_proposal(path, proposal)
    return proposal


def mark_harness_proposal_submitted(
    root: Any,
    proposal_id: str,
    draft_id: str,
    *,
    actor: str = "local",
    submitted_at: Optional[Any] = None,
) -> HarnessProposal:
    path = _prepare_root(root)
    proposal = load_harness_proposal(path, proposal_id)
    if proposal.status != "pending":
        raise HarnessProposalError("submit requires a pending proposal")
    existing = str(proposal.review.get("draft_id") or "")
    if existing and existing != draft_id:
        raise HarnessProposalError("proposal already submitted with another draft")
    proposal.review.update(
        {
            "draft_id": str(draft_id),
            "submitted_by": str(actor),
            "submitted_at": _format_time(submitted_at),
        }
    )
    _record_event(
        proposal,
        "submitted",
        actor=actor,
        at=submitted_at,
        details={"draft_id": str(draft_id)},
    )
    _save_proposal(path, proposal)
    return proposal


def adopt_harness_proposal(
    root: Any,
    proposal_id: str,
    *,
    actor: str = "local",
    adopted_at: Optional[Any] = None,
) -> Dict[str, Any]:
    """采纳已批准提案；失败时恢复采纳前 snapshot。"""
    path = _prepare_root(root)
    proposal = load_harness_proposal(path, proposal_id)
    if proposal.status != "approved":
        raise HarnessProposalError("adopt requires an approved proposal")
    verification = _require_base_current(path, proposal, mark_stale=True)
    _validate_selected_evidence(path, proposal)
    proposal_dir = _proposal_dir(path, proposal.proposal_id)
    snapshot_id = "pre-proposal-{}-{}".format(
        _format_time(adopted_at).replace("-", "").replace(":", "").replace("Z", ""),
        uuid.uuid4().hex[:8],
    )
    snapshot = create_harness_snapshot(path, snapshot_id, created_at=adopted_at)
    proposal.status = "adopting"
    proposal.adoption = {
        "pre_snapshot_id": snapshot.snapshot_id,
        "actor": str(actor),
        "started_at": _format_time(adopted_at),
    }
    _record_event(
        proposal,
        "adopting",
        actor=actor,
        at=adopted_at,
        details={"pre_snapshot_id": snapshot.snapshot_id},
    )
    _save_proposal(path, proposal)
    try:
        metadata: Dict[str, HarnessFileEntry] = dict(verification.lock.by_path)
        for edit in proposal.selected_edits:
            old = metadata.get(edit.path)
            if edit.operation == "delete":
                _delete_file(path, edit.path)
                metadata.pop(edit.path, None)
                continue
            data = _read_artifact(
                proposal_dir,
                "composed/files/" + edit.path,
                edit.after_sha256,
                "composed file",
            )
            _atomic_write(path, edit.path, data)
            metadata[edit.path] = HarnessFileEntry(
                path=edit.path,
                sha256=edit.after_sha256 or _sha256(data),
                size=len(data),
                component=old.component if old else infer_harness_component(edit.path),
                provenance="harness-proposal:" + proposal.proposal_id,
                owner=proposal.author,
                authority=old.authority if old else "configuration" if edit.path == "plugins.yaml" else "projection",
            )
        files, issues = _scan_files(path)
        _raise_for_issues(issues)
        entries = _entries_from_files(files, metadata)
        lock = _build_lock(
            entries,
            generated_at=adopted_at,
            generator="harness proposal " + proposal.proposal_id,
            startup_enforced=verification.lock.startup_enforced,
        )
        _write_lock(path, lock)
        checked = verify_harness_files(path)
        if not checked.valid:
            _raise_for_issues(checked.issues)
            raise HarnessProposalError("adopted harness files failed verification")
    except BaseException as exc:
        try:
            rollback_harness_files(path, snapshot.snapshot_id, create_pre_snapshot=False)
        except BaseException as rollback_exc:  # noqa: BLE001 - 保留 adopting 供人工恢复
            raise HarnessProposalError(
                f"proposal adoption failed and rollback failed: {rollback_exc}"
            ) from exc
        proposal.status = "approved"
        proposal.adoption.update(
            {"failed_at": _format_time(None), "error": f"{type(exc).__name__}: {exc}"}
        )
        _record_event(proposal, "adoption_failed", actor=actor)
        _save_proposal(path, proposal)
        if isinstance(exc, HarnessFilesError):
            raise
        raise HarnessProposalError(str(exc)) from exc

    proposal.status = "adopted"
    proposal.adoption.update(
        {
            "adopted_at": _format_time(adopted_at),
            "adopted_lock_content_sha256": lock.content_sha256,
            "changed_files": [item.path for item in proposal.selected_edits],
        }
    )
    _record_event(
        proposal,
        "adopted",
        actor=actor,
        at=adopted_at,
        details={"pre_snapshot_id": snapshot.snapshot_id},
    )
    _save_proposal(path, proposal)
    return {
        "root": str(path),
        "proposal": proposal.to_dict(),
        "pre_snapshot": snapshot.to_dict(),
        "lock": lock.to_dict(),
        "changed_files": [item.path for item in proposal.selected_edits],
    }


def rollback_harness_proposal(
    root: Any,
    proposal_id: str,
    *,
    actor: str = "local",
    force: bool = False,
    rolled_back_at: Optional[Any] = None,
) -> Dict[str, Any]:
    """把已采纳提案恢复到采纳前 snapshot。"""
    path = _prepare_root(root)
    proposal = load_harness_proposal(path, proposal_id)
    if proposal.status != "adopted":
        raise HarnessProposalError("rollback requires an adopted proposal")
    snapshot_id = str(proposal.adoption.get("pre_snapshot_id") or "")
    if not snapshot_id:
        raise HarnessProposalError("proposal adoption snapshot is missing")
    verification = verify_harness_files(path)
    adopted_sha = str(proposal.adoption.get("adopted_lock_content_sha256") or "")
    if not force and (
        not verification.valid
        or verification.lock is None
        or verification.lock.content_sha256 != adopted_sha
    ):
        raise HarnessProposalError(
            "harness files changed after proposal adoption; rollback requires force"
        )
    result = rollback_harness_files(path, snapshot_id, create_pre_snapshot=True)
    checked = verify_harness_files(path)
    if (
        not checked.valid
        or checked.lock is None
        or checked.lock.content_sha256 != proposal.base_lock_content_sha256
    ):
        raise HarnessProposalError("proposal rollback did not restore the base lock")
    proposal.status = "rolled_back"
    proposal.adoption.update(
        {
            "rolled_back_at": _format_time(rolled_back_at),
            "rollback_snapshot_id": snapshot_id,
            "pre_rollback_snapshot": result.get("pre_snapshot"),
        }
    )
    _record_event(
        proposal,
        "rolled_back",
        actor=actor,
        at=rolled_back_at,
        details={"snapshot_id": snapshot_id, "force": bool(force)},
    )
    _save_proposal(path, proposal)
    return {
        "root": str(path),
        "proposal": proposal.to_dict(),
        "rollback": result,
    }
