# ruff: noqa: UP006, UP007, UP035
"""R85 LLM 双候选与 SkillDraft 审批桥。"""

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.application.kernel.harness_evidence import create_harness_evidence
from backend.application.kernel.harness_files import HarnessFileSpec, verify_harness_files
from backend.application.kernel.harness_proposal_engine import (
    compose_harness_proposal,
    record_harness_probe,
)
from backend.application.kernel.harness_proposals import (
    create_harness_proposal,
    load_harness_proposal,
)
from backend.application.kernel.harness_snapshots import write_harness_files
from backend.skills.draft_store import SkillDraftStore
from backend.skills.harness_proposal_bridge import (
    approve_harness_proposal_draft,
    is_harness_proposal_draft,
    reject_harness_proposal_draft,
    submit_harness_proposal,
)
from backend.skills.harness_proposal_service import (
    HarnessProposalGenerationError,
    HarnessProposalService,
)
from backend.skills.review_service import ReviewService

FIXED_TIME = "2026-10-21T00:00:00Z"
EVIDENCE_ID = "ev-tool-errors-001"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS skill_drafts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    when_to_use TEXT NOT NULL,
    content TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    source_session_id TEXT,
    source_context TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at INTEGER NOT NULL,
    reviewed_at INTEGER,
    reviewed_by_user_id TEXT
)
"""


def _setup(tmp_path: Path):
    root = tmp_path / "harness"
    write_harness_files(
        root,
        [
            HarnessFileSpec(
                "plugins.yaml",
                "harness_config:\n  preset: standard\n",
                component="plugins",
                provenance="test:plugins",
                authority="configuration",
            ),
            HarnessFileSpec(
                "system.md",
                "be helpful\n",
                component="system",
                provenance="test:system",
            ),
        ],
        generated_at=FIXED_TIME,
    )
    create_harness_evidence(
        root,
        EVIDENCE_ID,
        "tool_trajectory",
        {"session_id": "session-1", "tool": "bash"},
        excerpt="browser tools were repeatedly loaded for a focused coding task.",
        metrics={"tool_error_rate": 0.2},
        created_at=FIXED_TIME,
    )
    db_path = tmp_path / "drafts.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(_CREATE_TABLE_SQL)
    return root, SkillDraftStore(str(db_path))


def _pending(root: Path, proposal_id: str):
    proposal = create_harness_proposal(
        root,
        title="Focus bundles for coding",
        summary="Use the existing focus preset for repeated coding sessions.",
        candidates=[
            {
                "id": "invariant",
                "lane": "invariant",
                "edits": [
                    {
                        "path": "plugins.yaml",
                        "content": "harness_config:\n  preset: focus\n",
                        "evidence_ids": [EVIDENCE_ID],
                    }
                ],
            }
        ],
        proposal_id=proposal_id,
        created_at=FIXED_TIME,
    )
    record_harness_probe(
        root,
        proposal_id,
        {
            "dataset": {"id": "replay-001", "evidence_ids": [EVIDENCE_ID]},
            "base_metrics": {"tool_error_rate": 0.2, "success_rate": 0.7},
            "candidates": {
                "invariant": {
                    "metrics": {"tool_error_rate": 0.1, "success_rate": 0.8},
                    "edits": {
                        "plugins.yaml": {
                            "supported": True,
                            "evidence_ids": [EVIDENCE_ID],
                        }
                    },
                }
            },
        },
    )
    compose_harness_proposal(root, proposal_id)
    return proposal


class _FakeProvider:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def complete(self, *, model, messages):
        self.calls.append((model, messages))
        return SimpleNamespace(text=json.dumps(self.payload))


def _generated_payload(evidence_id=EVIDENCE_ID):
    return {
        "title": "Focus coding harness",
        "summary": "Reduce irrelevant tool surface during coding trajectories.",
        "candidates": [
            {
                "id": "invariant",
                "lane": "invariant",
                "summary": "Use focus preset",
                "content": "harness_config:\n  preset: focus\n",
                "rationale": "trajectory shows irrelevant bundles",
                "evidence_ids": [evidence_id],
            },
            {
                "id": "domain",
                "lane": "domain",
                "summary": "Use dev preset",
                "content": "harness_config:\n  preset: dev\n",
                "rationale": "coding trajectory benefits from dev declarations",
                "evidence_ids": [evidence_id],
            },
        ],
    }


def test_llm_generation_creates_two_draft_candidates_without_mutation(
    tmp_path: Path,
) -> None:
    root, _store = _setup(tmp_path)
    provider = _FakeProvider(_generated_payload())
    service = HarnessProposalService(ReviewService(provider, model="test-model"))

    proposal = asyncio.run(
        service.generate(
            root,
            target_path="plugins.yaml",
            goal="Reduce irrelevant tool bundles",
            evidence_ids=[EVIDENCE_ID],
            proposal_id="prop-generated-001",
            created_at=FIXED_TIME,
        )
    )

    assert proposal.status == "draft"
    assert [item.lane for item in proposal.candidates] == ["invariant", "domain"]
    assert provider.calls[0][0] == "test-model"
    assert (root / "plugins.yaml").read_text(encoding="utf-8") == (
        "harness_config:\n  preset: standard\n"
    )
    assert verify_harness_files(root).valid is True


def test_llm_generation_rejects_unanchored_evidence(tmp_path: Path) -> None:
    root, _store = _setup(tmp_path)
    provider = _FakeProvider(_generated_payload("ev-not-supplied"))
    service = HarnessProposalService(ReviewService(provider, model="test-model"))

    with pytest.raises(HarnessProposalGenerationError, match="unknown evidence"):
        asyncio.run(
            service.generate(
                root,
                target_path="plugins.yaml",
                goal="Reduce irrelevant tool bundles",
                evidence_ids=[EVIDENCE_ID],
                proposal_id="prop-generated-bad",
            )
        )
    assert not (root / "proposals" / "prop-generated-bad").exists()


def test_submit_is_idempotent_and_approve_adopts(tmp_path: Path) -> None:
    root, store = _setup(tmp_path)
    proposal = _pending(root, "prop-bridge-adopt")

    first = submit_harness_proposal(root, proposal.proposal_id, draft_store=store)
    second = submit_harness_proposal(root, proposal.proposal_id, draft_store=store)

    assert first.id == second.id
    assert is_harness_proposal_draft(first) is True
    assert first.source_context["proposal_id"] == proposal.proposal_id
    assert "preset: focus" in first.content
    assert load_harness_proposal(root, proposal.proposal_id).review["draft_id"] == first.id

    result = approve_harness_proposal_draft(first, store, actor="reviewer")

    assert result["changed_files"] == ["plugins.yaml"]
    assert "preset: focus" in (root / "plugins.yaml").read_text(encoding="utf-8")
    assert verify_harness_files(root).valid is True
    assert store.get(first.id).status == "approved"
    assert load_harness_proposal(root, proposal.proposal_id).status == "adopted"


def test_bridge_reject_marks_proposal_without_mutation(tmp_path: Path) -> None:
    root, store = _setup(tmp_path)
    proposal = _pending(root, "prop-bridge-reject")
    draft = submit_harness_proposal(root, proposal.proposal_id, draft_store=store)

    reject_harness_proposal_draft(draft, store, actor="reviewer")

    assert "preset: standard" in (root / "plugins.yaml").read_text(encoding="utf-8")
    assert store.get(draft.id).status == "rejected"
    assert load_harness_proposal(root, proposal.proposal_id).status == "rejected"
