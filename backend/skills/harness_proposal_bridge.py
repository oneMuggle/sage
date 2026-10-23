# ruff: noqa: UP006, UP007, UP035
"""HarnessProposal 与既有 SkillDraft 审批队列的镜像桥（R85）。"""

from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from backend.application.kernel.harness_evidence import HarnessProposalError
from backend.application.kernel.harness_proposal_engine import (
    adopt_harness_proposal,
    approve_harness_proposal,
    mark_harness_proposal_submitted,
    reject_harness_proposal,
)
from backend.application.kernel.harness_proposals import (
    load_harness_proposal,
    render_harness_proposal_review,
)
from backend.skills.draft_store import SkillDraftStore, get_skill_draft_store
from backend.skills.review_service import SkillDraft

HARNESS_PROPOSAL_TRIGGER = "harness_proposal"
HARNESS_PROPOSAL_CONTEXT_KIND = "harness_proposal"


class HarnessProposalBridgeError(HarnessProposalError):
    """harness 提案镜像与文件仓状态不一致。"""


def is_harness_proposal_draft(draft: Any) -> bool:
    context = getattr(draft, "source_context", None)
    return bool(
        getattr(draft, "trigger_type", None) == HARNESS_PROPOSAL_TRIGGER
        and isinstance(context, Mapping)
        and context.get("kind") == HARNESS_PROPOSAL_CONTEXT_KIND
    )


def _proposal_ref(draft: Any) -> Tuple[Path, str]:
    if not is_harness_proposal_draft(draft):
        raise HarnessProposalBridgeError("draft is not a harness proposal")
    context = draft.source_context
    root = str(context.get("harness_root") or "").strip()
    proposal_id = str(context.get("proposal_id") or "").strip()
    if not root or not proposal_id:
        raise HarnessProposalBridgeError("harness proposal draft reference is incomplete")
    return Path(root), proposal_id


def _draft_name(proposal: Any) -> str:
    digest = hashlib.sha256(proposal.proposal_id.encode("utf-8")).hexdigest()[:8]
    return f"harness-{proposal.component}-{digest}"


def build_harness_proposal_draft(
    root: Any,
    proposal_id: str,
    *,
    draft_id: Optional[str] = None,
    created_at_ms: Optional[int] = None,
) -> SkillDraft:
    """把 pending 提案渲染为既有审批队列可展示的一条 SkillDraft。"""
    proposal = load_harness_proposal(root, proposal_id)
    if proposal.status != "pending":
        raise HarnessProposalBridgeError("harness proposal draft requires a pending proposal")
    root_path = Path(root).expanduser().resolve()
    return SkillDraft(
        id=draft_id or str(uuid.uuid4()),
        name=_draft_name(proposal),
        description=f"Harness 行为提案：{proposal.title}（批准即按快照采纳）",
        when_to_use=f"审阅 harness {proposal.component} 组件的离线提案；批准后修改锁定文件，拒绝不生效。",
        content=render_harness_proposal_review(root_path, proposal.proposal_id),
        trigger_type=HARNESS_PROPOSAL_TRIGGER,
        source_session_id="harness:" + proposal.proposal_id,
        source_context={
            "kind": HARNESS_PROPOSAL_CONTEXT_KIND,
            "proposal_id": proposal.proposal_id,
            "harness_root": str(root_path),
            "component": proposal.component,
            "base_lock_content_sha256": proposal.base_lock_content_sha256,
            "selected_paths": [item.path for item in proposal.selected_edits],
        },
        status="pending",
        created_at=int(time.time() * 1000) if created_at_ms is None else int(created_at_ms),
    )


def _require_bound_draft(proposal: Any, draft: SkillDraft) -> None:
    bound = str(proposal.review.get("draft_id") or "")
    if bound and bound != draft.id:
        raise HarnessProposalBridgeError("draft is not bound to this harness proposal")


def submit_harness_proposal(
    root: Any,
    proposal_id: str,
    *,
    draft_store: Optional[SkillDraftStore] = None,
    db_path: Optional[str] = None,
    actor: str = "local",
    draft_id: Optional[str] = None,
    created_at_ms: Optional[int] = None,
) -> SkillDraft:
    """幂等提交到 SkillDraft 待审队列。"""
    proposal = load_harness_proposal(root, proposal_id)
    if proposal.status != "pending":
        raise HarnessProposalBridgeError("submit requires a pending harness proposal")
    store = draft_store or get_skill_draft_store(db_path)
    root_path = Path(root).expanduser().resolve()
    existing_id = str(proposal.review.get("draft_id") or "")
    if existing_id:
        existing = store.get(existing_id)
        if existing is None:
            raise HarnessProposalBridgeError("submitted harness draft is missing")
        ref_root, ref_id = _proposal_ref(existing)
        if ref_root != root_path or ref_id != proposal.proposal_id:
            raise HarnessProposalBridgeError("submitted draft points to another proposal")
        if existing.status != "pending":
            raise HarnessProposalBridgeError("harness proposal draft was already reviewed")
        return existing
    for existing in store.list(status="pending"):
        if not is_harness_proposal_draft(existing):
            continue
        try:
            ref_root, ref_id = _proposal_ref(existing)
        except HarnessProposalBridgeError:
            continue
        if ref_root == root_path and ref_id == proposal.proposal_id:
            mark_harness_proposal_submitted(
                root_path, proposal.proposal_id, existing.id, actor=actor
            )
            return existing
    draft = build_harness_proposal_draft(
        root_path,
        proposal.proposal_id,
        draft_id=draft_id,
        created_at_ms=created_at_ms,
    )
    store.insert(draft)
    mark_harness_proposal_submitted(
        root_path, proposal.proposal_id, draft.id, actor=actor
    )
    return store.get(draft.id) or draft


def approve_harness_proposal_draft(
    draft: SkillDraft,
    draft_store: SkillDraftStore,
    *,
    actor: str = "user",
) -> Dict[str, Any]:
    """批准镜像草稿并立即按 snapshot 采纳 harness 提案。"""
    root, proposal_id = _proposal_ref(draft)
    if draft.status != "pending":
        raise HarnessProposalBridgeError("harness proposal draft is not pending")
    proposal = load_harness_proposal(root, proposal_id)
    _require_bound_draft(proposal, draft)
    if proposal.status == "adopted":
        draft_store.update_status(draft.id, "approved", reviewed_by=actor)
        return {"proposal": proposal.to_dict(), "already_adopted": True}
    if proposal.status == "pending":
        approve_harness_proposal(root, proposal_id, actor=actor)
    elif proposal.status != "approved":
        raise HarnessProposalBridgeError(
            "harness proposal cannot be adopted from status " + proposal.status
        )
    result = adopt_harness_proposal(root, proposal_id, actor=actor)
    draft_store.update_status(draft.id, "approved", reviewed_by=actor)
    return result


def reject_harness_proposal_draft(
    draft: SkillDraft,
    draft_store: SkillDraftStore,
    *,
    actor: str = "user",
) -> Dict[str, Any]:
    """拒绝镜像草稿；不修改托管 harness 文件。"""
    root, proposal_id = _proposal_ref(draft)
    if draft.status != "pending":
        raise HarnessProposalBridgeError("harness proposal draft is not pending")
    proposal = load_harness_proposal(root, proposal_id)
    _require_bound_draft(proposal, draft)
    if proposal.status == "adopted":
        raise HarnessProposalBridgeError("adopted harness proposal cannot be rejected")
    if proposal.status != "rejected":
        proposal = reject_harness_proposal(root, proposal_id, actor=actor)
    draft_store.update_status(draft.id, "rejected", reviewed_by=actor)
    return {"proposal": proposal.to_dict()}
