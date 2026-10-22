# ruff: noqa: UP006, UP007, UP035
"""HarnessProposal 文件仓、候选物化与审阅视图（R85）。"""

from __future__ import annotations

import base64
import binascii
import difflib
import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from backend.application.kernel.harness_evidence import (
    _ALLOWED_COMPONENTS,
    _SHA256_RE,
    _STATUSES,
    _TRAJECTORY_KINDS,
    MAX_CANDIDATES,
    MAX_EDITS_PER_CANDIDATE,
    MAX_MANIFEST_BYTES,
    MAX_PATCH_CHARS,
    MAX_PROBE_BYTES,
    PROPOSAL_KIND,
    PROPOSAL_SCHEMA_VERSION,
    PROPOSALS_DIR_NAME,
    EvidenceRecord,
    HarnessProposalError,
    _canonical_json,
    _evidence_path,
    _new_id,
    _parse_evidence_payload,
    _sha256,
    _validate_id,
    _write_evidence_record,
    load_harness_evidence,
)
from backend.application.kernel.harness_files import (
    MAX_HARNESS_FILE_BYTES,
    MAX_HARNESS_TOTAL_BYTES,
    HarnessFilesError,
    _atomic_write,
    _format_time,
    _prepare_root,
    _raise_for_issues,
    _safe_target,
    _validate_managed_path,
    infer_harness_component,
    verify_harness_files,
)

__all__ = [
    "HarnessProposal",
    "ProposalCandidate",
    "ProposalEdit",
    "create_harness_proposal",
    "harness_proposal_view",
    "list_harness_proposals",
    "load_harness_proposal",
    "render_harness_proposal_review",
]

@dataclass(frozen=True)
class ProposalEdit:
    path: str
    operation: str
    base_sha256: Optional[str]
    after_sha256: Optional[str]
    size: int
    evidence_ids: Tuple[str, ...]
    rationale: str = ""
    candidate_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "operation": self.operation,
            "base_sha256": self.base_sha256,
            "after_sha256": self.after_sha256,
            "size": self.size,
            "evidence_ids": list(self.evidence_ids),
            "rationale": self.rationale,
            "candidate_id": self.candidate_id,
        }


@dataclass(frozen=True)
class ProposalCandidate:
    candidate_id: str
    lane: str
    summary: str
    edits: Tuple[ProposalEdit, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.candidate_id,
            "lane": self.lane,
            "summary": self.summary,
            "edits": [edit.to_dict() for edit in self.edits],
        }


@dataclass()
class HarnessProposal:
    proposal_id: str
    title: str
    summary: str
    author: str
    component: str
    status: str
    created_at: str
    updated_at: str
    base_lock_content_sha256: str
    candidates: Tuple[ProposalCandidate, ...]
    selected_edits: Tuple[ProposalEdit, ...] = ()
    probe: Dict[str, Any] = field(default_factory=dict)
    compose: Dict[str, Any] = field(default_factory=dict)
    review: Dict[str, Any] = field(default_factory=dict)
    adoption: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    manifest_sha256: str = ""

    def payload(self) -> Dict[str, Any]:
        return {
            "schema_version": PROPOSAL_SCHEMA_VERSION,
            "kind": PROPOSAL_KIND,
            "id": self.proposal_id,
            "title": self.title,
            "summary": self.summary,
            "author": self.author,
            "component": self.component,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "base_lock_content_sha256": self.base_lock_content_sha256,
            "candidates": [item.to_dict() for item in self.candidates],
            "selected_edits": [item.to_dict() for item in self.selected_edits],
            "probe": self.probe,
            "compose": self.compose,
            "review": self.review,
            "adoption": self.adoption,
            "history": self.history,
        }

    def to_dict(self) -> Dict[str, Any]:
        payload = self.payload()
        payload["manifest_sha256"] = self.manifest_sha256 or _sha256(_canonical_json(payload))
        return payload


def _edit_from_dict(raw: Any) -> ProposalEdit:
    if not isinstance(raw, Mapping):
        raise HarnessProposalError("proposal edit must be an object")
    path = _validate_managed_path(str(raw.get("path") or ""))
    operation = str(raw.get("operation") or "")
    if operation not in ("write", "delete"):
        raise HarnessProposalError("invalid proposal edit operation: " + path)
    base_sha = raw.get("base_sha256")
    after_sha = raw.get("after_sha256")
    for value in (base_sha, after_sha):
        if value is not None and (not isinstance(value, str) or not _SHA256_RE.match(value)):
            raise HarnessProposalError("invalid edit hash: " + path)
    size = raw.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise HarnessProposalError("invalid edit size: " + path)
    raw_ids = raw.get("evidence_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raise HarnessProposalError("proposal edit requires evidence: " + path)
    evidence_ids = tuple(_validate_id(item, "evidence id") for item in raw_ids)
    return ProposalEdit(
        path=path,
        operation=operation,
        base_sha256=base_sha,
        after_sha256=after_sha,
        size=size,
        evidence_ids=evidence_ids,
        rationale=str(raw.get("rationale") or ""),
        candidate_id=str(raw.get("candidate_id") or ""),
    )


def _candidate_from_dict(raw: Any) -> ProposalCandidate:
    if not isinstance(raw, Mapping):
        raise HarnessProposalError("proposal candidate must be an object")
    candidate_id = _validate_id(raw.get("id"), "candidate id")
    lane = _validate_id(raw.get("lane") or candidate_id, "candidate lane")
    edits_raw = raw.get("edits")
    if not isinstance(edits_raw, list) or not edits_raw:
        raise HarnessProposalError("proposal candidate requires edits: " + candidate_id)
    return ProposalCandidate(
        candidate_id,
        lane,
        str(raw.get("summary") or ""),
        tuple(_edit_from_dict(item) for item in edits_raw),
    )


def _proposal_from_dict(raw: Any) -> HarnessProposal:
    if not isinstance(raw, Mapping):
        raise HarnessProposalError("proposal manifest must be an object")
    if raw.get("schema_version") != PROPOSAL_SCHEMA_VERSION or raw.get("kind") != PROPOSAL_KIND:
        raise HarnessProposalError("unsupported proposal manifest")
    payload = dict(raw)
    manifest_sha = payload.pop("manifest_sha256", None)
    expected = _sha256(_canonical_json(payload))
    if manifest_sha != expected:
        raise HarnessProposalError("proposal manifest hash mismatch")
    status = str(raw.get("status") or "")
    if status not in _STATUSES:
        raise HarnessProposalError("invalid proposal status: " + repr(status))
    candidates_raw = raw.get("candidates")
    if not isinstance(candidates_raw, list) or not candidates_raw:
        raise HarnessProposalError("proposal requires candidates")
    selected_raw = raw.get("selected_edits") or []
    if not isinstance(selected_raw, list):
        raise HarnessProposalError("selected_edits must be a list")
    dict_fields = {}
    for key in ("probe", "compose", "review", "adoption"):
        value = raw.get(key) or {}
        if not isinstance(value, Mapping):
            raise HarnessProposalError(key + " must be an object")
        dict_fields[key] = dict(value)
    history = raw.get("history") or []
    if not isinstance(history, list):
        raise HarnessProposalError("proposal history must be a list")
    return HarnessProposal(
        proposal_id=_validate_id(raw.get("id"), "proposal id"),
        title=str(raw.get("title") or ""),
        summary=str(raw.get("summary") or ""),
        author=str(raw.get("author") or "local"),
        component=str(raw.get("component") or ""),
        status=status,
        created_at=str(raw.get("created_at") or ""),
        updated_at=str(raw.get("updated_at") or ""),
        base_lock_content_sha256=str(raw.get("base_lock_content_sha256") or ""),
        candidates=tuple(_candidate_from_dict(item) for item in candidates_raw),
        selected_edits=tuple(_edit_from_dict(item) for item in selected_raw),
        probe=dict_fields["probe"],
        compose=dict_fields["compose"],
        review=dict_fields["review"],
        adoption=dict_fields["adoption"],
        history=[dict(item) for item in history if isinstance(item, Mapping)],
        manifest_sha256=expected,
    )


def _proposal_dir(root: Path, proposal_id: str) -> Path:
    return _safe_target(root, f"{PROPOSALS_DIR_NAME}/{proposal_id}/proposal.json").parent


def _write_manifest(proposal_dir: Path, proposal: HarnessProposal) -> None:
    proposal.manifest_sha256 = _sha256(_canonical_json(proposal.payload()))
    payload = json.dumps(proposal.to_dict(), ensure_ascii=False, indent=2) + "\n"
    data = payload.encode("utf-8")
    if len(data) > MAX_MANIFEST_BYTES:
        raise HarnessProposalError("proposal manifest exceeds size limit")
    _atomic_write(proposal_dir, "proposal.json", data)


def _record_event(
    proposal: HarnessProposal,
    event: str,
    *,
    actor: str = "local",
    at: Optional[Any] = None,
    details: Optional[Mapping[str, Any]] = None,
) -> None:
    moment = _format_time(at)
    proposal.updated_at = moment
    proposal.history.append(
        {
            "event": event,
            "actor": str(actor or "local"),
            "at": moment,
            "details": dict(details or {}),
        }
    )


def _save_proposal(root: Path, proposal: HarnessProposal) -> None:
    _write_manifest(_proposal_dir(root, proposal.proposal_id), proposal)


def _read_artifact(base: Path, relative: str, expected_sha: Optional[str], label: str) -> bytes:
    target = _safe_target(base, relative)
    if target.is_symlink() or not target.is_file():
        raise HarnessProposalError(label + " is missing: " + relative)
    if target.stat().st_size > MAX_HARNESS_FILE_BYTES:
        raise HarnessProposalError(label + " exceeds size limit: " + relative)
    data = target.read_bytes()
    if expected_sha is not None and _sha256(data) != expected_sha:
        raise HarnessProposalError(label + " hash mismatch: " + relative)
    return data


def _verify_artifacts(proposal_dir: Path, proposal: HarnessProposal) -> None:
    for candidate in proposal.candidates:
        seen = set()
        for edit in candidate.edits:
            if edit.path in seen:
                raise HarnessProposalError("duplicate candidate edit: " + edit.path)
            seen.add(edit.path)
            if edit.base_sha256 is not None:
                _read_artifact(
                    proposal_dir, "base/files/" + edit.path, edit.base_sha256, "base file"
                )
            if edit.operation == "write":
                data = _read_artifact(
                    proposal_dir,
                    f"candidates/{candidate.candidate_id}/files/{edit.path}",
                    edit.after_sha256,
                    "candidate file",
                )
                if len(data) != edit.size:
                    raise HarnessProposalError("candidate file size mismatch: " + edit.path)
    for edit in proposal.selected_edits:
        if edit.operation == "write":
            _read_artifact(
                proposal_dir, "composed/files/" + edit.path, edit.after_sha256, "composed file"
            )
    if proposal.probe:
        report = proposal.probe.get("report")
        probe_sha = proposal.probe.get("probe_sha256")
        if not isinstance(report, Mapping) or probe_sha != _sha256(_canonical_json(report)):
            raise HarnessProposalError("probe report hash mismatch")
        probe_file = _safe_target(proposal_dir, "probe.json")
        if probe_file.is_symlink() or not probe_file.is_file():
            raise HarnessProposalError("probe report file is missing")
        if probe_file.stat().st_size > MAX_PROBE_BYTES:
            raise HarnessProposalError("probe report exceeds size limit")
        try:
            stored = json.loads(probe_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise HarnessProposalError("invalid probe report file") from exc
        if stored != report:
            raise HarnessProposalError("probe report file differs from manifest")


def _load_from_dir(proposal_dir: Path, *, verify_artifacts: bool = True) -> HarnessProposal:
    manifest_path = _safe_target(proposal_dir, "proposal.json")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise HarnessProposalError("proposal not found: " + proposal_dir.name)
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise HarnessProposalError("proposal manifest exceeds size limit")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise HarnessProposalError(f"invalid proposal manifest: {exc}") from exc
    proposal = _proposal_from_dict(raw)
    if proposal_dir.name not in (proposal.proposal_id,) and not proposal_dir.name.startswith(
        ".staging-"
    ):
        raise HarnessProposalError("proposal directory id mismatch")
    if verify_artifacts:
        _verify_artifacts(proposal_dir, proposal)
    return proposal


def load_harness_proposal(
    root: Any, proposal_id: str, *, verify_artifacts: bool = True
) -> HarnessProposal:
    path = _prepare_root(root)
    selected = _validate_id(proposal_id, "proposal id")
    return _load_from_dir(_proposal_dir(path, selected), verify_artifacts=verify_artifacts)


def list_harness_proposals(
    root: Any, *, status: Optional[str] = None
) -> List[HarnessProposal]:
    path = _prepare_root(root)
    directory = path / PROPOSALS_DIR_NAME
    if not directory.exists():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise HarnessProposalError("proposals directory is invalid")
    result: List[HarnessProposal] = []
    for child in directory.iterdir():
        if child.name.startswith(".") or child.is_symlink() or not child.is_dir():
            continue
        try:
            proposal = _load_from_dir(child)
        except HarnessFilesError:
            continue
        if status is None or proposal.status == status:
            result.append(proposal)
    result.sort(key=lambda item: (item.updated_at, item.proposal_id), reverse=True)
    return result


def _content_bytes(raw: Mapping[str, Any], path: str) -> bytes:
    has_text = "content" in raw
    has_b64 = "content_base64" in raw
    if has_text == has_b64:
        raise HarnessProposalError("write edit requires exactly one content field: " + path)
    if has_b64:
        try:
            return base64.b64decode(str(raw["content_base64"]), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HarnessProposalError("invalid content_base64: " + path) from exc
    value = raw["content"]
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise HarnessProposalError("write edit content must be text or bytes: " + path)


def create_harness_proposal(  # noqa: PLR0911 - 创建守卫逐项早返回
    root: Any,
    *,
    title: str,
    summary: str,
    candidates: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]] = (),
    author: str = "local",
    proposal_id: Optional[str] = None,
    created_at: Optional[Any] = None,
) -> HarnessProposal:
    """从当前有效 lock 创建一份 draft 提案，不修改托管文件。"""
    path = _prepare_root(root)
    if not str(title or "").strip() or len(str(title)) > 200:
        raise HarnessProposalError("proposal title is required and must be <= 200 chars")
    if not str(summary or "").strip() or len(str(summary)) > 4000:
        raise HarnessProposalError("proposal summary is required and must be <= 4000 chars")
    selected_id = _validate_id(proposal_id or _new_id("prop"), "proposal id")
    verification = verify_harness_files(path)
    if not verification.adopted or not verification.valid or verification.lock is None:
        _raise_for_issues(verification.issues)
        raise HarnessProposalError("proposal requires a valid adopted harness lock")
    lock = verification.lock
    target_dir = _proposal_dir(path, selected_id)
    if target_dir.exists() or target_dir.is_symlink():
        raise HarnessProposalError("proposal already exists: " + selected_id)

    embedded: Dict[str, EvidenceRecord] = {}
    for raw in evidence:
        record = _parse_evidence_payload(dict(raw), created_at)
        if record.evidence_id in embedded:
            raise HarnessProposalError("duplicate embedded evidence: " + record.evidence_id)
        embedded[record.evidence_id] = record
    evidence_cache: Dict[str, EvidenceRecord] = dict(embedded)

    def evidence_for(evidence_id: str) -> EvidenceRecord:
        if evidence_id not in evidence_cache:
            evidence_cache[evidence_id] = load_harness_evidence(path, evidence_id)
        record = evidence_cache[evidence_id]
        if evidence_id in embedded:
            target = _evidence_path(path, evidence_id)
            if target.is_file() and not target.is_symlink():
                existing = load_harness_evidence(path, evidence_id)
                if existing.payload() != record.payload():
                    raise HarnessProposalError(
                        "embedded evidence differs from stored record: " + evidence_id
                    )
        return record

    if not candidates or len(candidates) > MAX_CANDIDATES:
        raise HarnessProposalError("proposal requires 1-4 candidates")
    parsed_candidates: List[ProposalCandidate] = []
    candidate_data: Dict[Tuple[str, str], bytes] = {}
    base_data: Dict[str, bytes] = {}
    components = set()
    candidate_ids = set()
    total_bytes = 0
    for raw_candidate in candidates:
        if not isinstance(raw_candidate, Mapping):
            raise HarnessProposalError("proposal candidate must be an object")
        candidate_id = _validate_id(raw_candidate.get("id"), "candidate id")
        if candidate_id in candidate_ids:
            raise HarnessProposalError("duplicate candidate: " + candidate_id)
        candidate_ids.add(candidate_id)
        lane = _validate_id(raw_candidate.get("lane") or candidate_id, "candidate lane")
        raw_edits = raw_candidate.get("edits")
        if not isinstance(raw_edits, list) or not raw_edits or len(raw_edits) > MAX_EDITS_PER_CANDIDATE:
            raise HarnessProposalError("candidate requires 1-32 edits: " + candidate_id)
        edits: List[ProposalEdit] = []
        seen_paths = set()
        for raw_edit in raw_edits:
            if not isinstance(raw_edit, Mapping):
                raise HarnessProposalError("proposal edit must be an object")
            edit_path = _validate_managed_path(str(raw_edit.get("path") or ""))
            if edit_path in seen_paths:
                raise HarnessProposalError("duplicate candidate edit: " + edit_path)
            seen_paths.add(edit_path)
            component = infer_harness_component(edit_path)
            if component not in _ALLOWED_COMPONENTS:
                raise HarnessProposalError("proposal path is not an editable harness face: " + edit_path)
            components.add(component)
            operation = str(raw_edit.get("operation") or "write")
            if operation not in ("write", "delete"):
                raise HarnessProposalError("invalid proposal edit operation: " + edit_path)
            raw_ids = raw_edit.get("evidence_ids")
            if not isinstance(raw_ids, list) or not raw_ids:
                raise HarnessProposalError("proposal edit requires evidence: " + edit_path)
            evidence_ids = tuple(_validate_id(item, "evidence id") for item in raw_ids)
            records = [evidence_for(item) for item in evidence_ids]
            if not any(item.evidence_kind in _TRAJECTORY_KINDS for item in records):
                raise HarnessProposalError(
                    "proposal edit requires trajectory evidence: " + edit_path
                )
            base_entry = lock.by_path.get(edit_path)
            if base_entry is not None and edit_path not in base_data:
                base_bytes = _safe_target(path, edit_path).read_bytes()
                if _sha256(base_bytes) != base_entry.sha256:
                    raise HarnessProposalError("base file hash mismatch: " + edit_path)
                base_data[edit_path] = base_bytes
                total_bytes += len(base_bytes)
            if operation == "delete":
                if base_entry is None:
                    raise HarnessProposalError("cannot delete a missing harness file: " + edit_path)
                if "content" in raw_edit or "content_base64" in raw_edit:
                    raise HarnessProposalError("delete edit must not carry content: " + edit_path)
                after_sha = None
                size = 0
            else:
                data = _content_bytes(raw_edit, edit_path)
                if len(data) > MAX_HARNESS_FILE_BYTES:
                    raise HarnessProposalError("candidate file exceeds size limit: " + edit_path)
                after_sha = _sha256(data)
                if base_entry is not None and after_sha == base_entry.sha256:
                    raise HarnessProposalError("proposal edit is a no-op: " + edit_path)
                candidate_data[(candidate_id, edit_path)] = data
                size = len(data)
                total_bytes += size
            if total_bytes > MAX_HARNESS_TOTAL_BYTES:
                raise HarnessProposalError("proposal artifacts exceed total size limit")
            edits.append(
                ProposalEdit(
                    path=edit_path,
                    operation=operation,
                    base_sha256=base_entry.sha256 if base_entry else None,
                    after_sha256=after_sha,
                    size=size,
                    evidence_ids=evidence_ids,
                    rationale=str(raw_edit.get("rationale") or ""),
                )
            )
        parsed_candidates.append(
            ProposalCandidate(
                candidate_id,
                lane,
                str(raw_candidate.get("summary") or ""),
                tuple(edits),
            )
        )
    if len(components) != 1:
        raise HarnessProposalError("proposal must touch exactly one harness component")
    component = next(iter(components))

    for record in embedded.values():
        if not _evidence_path(path, record.evidence_id).is_file():
            _write_evidence_record(path, record)

    moment = _format_time(created_at)
    proposal = HarnessProposal(
        proposal_id=selected_id,
        title=str(title).strip(),
        summary=str(summary).strip(),
        author=str(author or "local"),
        component=component,
        status="draft",
        created_at=moment,
        updated_at=moment,
        base_lock_content_sha256=lock.content_sha256,
        candidates=tuple(parsed_candidates),
    )
    _record_event(proposal, "created", actor=proposal.author, at=moment)
    proposals_dir = path / PROPOSALS_DIR_NAME
    if proposals_dir.is_symlink():
        raise HarnessProposalError("proposals directory must not be a symlink")
    proposals_dir.mkdir(parents=True, exist_ok=True)
    staging = proposals_dir / f".staging-{selected_id}-{uuid.uuid4().hex[:8]}"
    try:
        staging.mkdir(parents=False, exist_ok=False)
        for edit_path, data in sorted(base_data.items()):
            _atomic_write(staging, "base/files/" + edit_path, data)
        for (candidate_id, edit_path), data in sorted(candidate_data.items()):
            _atomic_write(
                staging,
                f"candidates/{candidate_id}/files/{edit_path}",
                data,
            )
        _write_manifest(staging, proposal)
        _load_from_dir(staging)
        staging.replace(target_dir)
    except BaseException:
        if staging.exists():
            shutil.rmtree(str(staging), ignore_errors=True)
        raise
    return load_harness_proposal(path, selected_id)
def _evidence_summary(root: Path, evidence_id: str) -> Dict[str, Any]:
    try:
        record = load_harness_evidence(root, evidence_id)
    except HarnessFilesError as exc:
        return {"id": evidence_id, "valid": False, "error": str(exc)}
    return {
        "id": record.evidence_id,
        "valid": True,
        "kind": record.evidence_kind,
        "source": record.source,
        "excerpt": record.excerpt,
        "excerpt_sha256": record.excerpt_sha256,
        "metrics": record.metrics,
        "evidence_sha256": record.evidence_sha256,
        "created_at": record.created_at,
    }


def _patch_for(before: Optional[bytes], after: Optional[bytes], path: str) -> Optional[str]:
    def decode(data: Optional[bytes]) -> Optional[str]:
        if data is None:
            return ""
        if len(data) > 256 * 1024:
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    before_text = decode(before)
    after_text = decode(after)
    if before_text is None or after_text is None:
        return None
    patch = "".join(
        difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile="a/" + path,
            tofile="b/" + path,
        )
    )
    if len(patch) > MAX_PATCH_CHARS:
        patch = patch[:MAX_PATCH_CHARS] + "\n... (truncated)\n"
    return patch


def harness_proposal_view(
    root: Any, proposal_id: str, *, include_patch: bool = False
) -> Dict[str, Any]:
    """构造提案的稳定 JSON 视图（含可选 diff）。"""
    path = _prepare_root(root)
    proposal = load_harness_proposal(path, proposal_id)
    proposal_dir = _proposal_dir(path, proposal.proposal_id)
    verification = verify_harness_files(path)
    base_current = bool(
        verification.valid
        and verification.lock is not None
        and verification.lock.content_sha256 == proposal.base_lock_content_sha256
    )
    evidence_ids: List[str] = []
    for candidate in proposal.candidates:
        for edit in candidate.edits:
            for evidence_id in edit.evidence_ids:
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
    report = proposal.probe.get("report") if isinstance(proposal.probe, Mapping) else None
    if isinstance(report, Mapping):
        dataset = report.get("dataset") or {}
        if isinstance(dataset, Mapping):
            for evidence_id in dataset.get("evidence_ids") or []:
                if str(evidence_id) not in evidence_ids:
                    evidence_ids.append(str(evidence_id))
    diff_entries: List[Dict[str, Any]] = []
    for edit in proposal.selected_edits:
        before = None
        if edit.base_sha256 is not None:
            before = _read_artifact(
                proposal_dir, "base/files/" + edit.path, edit.base_sha256, "base file"
            )
        after = None
        if edit.operation == "write":
            after = _read_artifact(
                proposal_dir, "composed/files/" + edit.path, edit.after_sha256, "composed file"
            )
        status = "added" if before is None else "deleted" if after is None else "modified"
        diff_entries.append(
            {
                "path": edit.path,
                "status": status,
                "operation": edit.operation,
                "candidate_id": edit.candidate_id,
                "before_sha256": edit.base_sha256,
                "after_sha256": edit.after_sha256,
                "before_size": len(before) if before is not None else None,
                "after_size": len(after) if after is not None else None,
                "patch": _patch_for(before, after, edit.path) if include_patch else None,
            }
        )
    view = proposal.to_dict()
    view.update(
        {
            "root": str(path),
            "base_current": base_current,
            "current_lock_content_sha256": (
                verification.lock.content_sha256 if verification.lock else None
            ),
            "evidence": [_evidence_summary(path, item) for item in evidence_ids],
            "diff": diff_entries,
        }
    )
    return view


def render_harness_proposal_review(root: Any, proposal_id: str) -> str:
    """把提案渲染为人工审批可读的 Markdown review packet。"""
    view = harness_proposal_view(root, proposal_id, include_patch=True)
    lines = [
        "# Harness 提案：{}".format(view["title"]),
        "",
        "> 批准后将按快照采纳到 fileized harness；拒绝不会修改托管文件。",
        "",
        "- Proposal ID：`{}`".format(view["id"]),
        "- Component：`{}`".format(view["component"]),
        "- Status：`{}`".format(view["status"]),
        "- Base lock：`{}`".format(view["base_lock_content_sha256"]),
        "- Base current：`{}`".format(view["base_current"]),
        "",
        "## 摘要",
        "",
        str(view["summary"]),
        "",
        "## Probe / Compose",
        "",
        "```json",
        json.dumps(view.get("compose") or {}, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Evidence",
        "",
    ]
    for item in view["evidence"]:
        if not item.get("valid"):
            lines.append("- `{}`：无效（{}）".format(item["id"], item.get("error")))
            continue
        excerpt = str(item.get("excerpt") or "").replace("\r\n", "\n")
        if len(excerpt) > 800:
            excerpt = excerpt[:800] + "…"
        lines.extend(
            [
                "### `{}`（{}）".format(item["id"], item["kind"]),
                "",
                "- Source：`{}`".format(json.dumps(item["source"], ensure_ascii=False, sort_keys=True)),
                "- Evidence SHA-256：`{}`".format(item["evidence_sha256"]),
                "",
                "> " + excerpt.replace("\n", "\n> "),
                "",
            ]
        )
    lines.extend(["## Diff", ""])
    if not view["diff"]:
        lines.append("（尚无 Compose 选中的编辑）")
    for entry in view["diff"]:
        lines.extend(
            [
                "### {} `{}`".format(entry["status"], entry["path"]),
                "",
                "````diff",
                str(entry.get("patch") or "(binary or oversized diff omitted)").rstrip(),
                "````",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
