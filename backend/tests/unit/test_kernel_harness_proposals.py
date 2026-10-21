# ruff: noqa: UP006, UP007, UP035
"""R85 harness proposal 文件仓、证据门、Compose 与采纳回滚。"""

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from backend.application.kernel.harness_evidence import (
    create_harness_evidence,
    load_harness_evidence,
)
from backend.application.kernel.harness_files import (
    HarnessFilesError,
    HarnessFileSpec,
    load_harness_lock,
    verify_harness_files,
)
from backend.application.kernel.harness_proposal_engine import (
    adopt_harness_proposal,
    approve_harness_proposal,
    compose_harness_proposal,
    record_harness_probe,
    rollback_harness_proposal,
    stage_harness_candidate,
)
from backend.application.kernel.harness_proposals import (
    create_harness_proposal,
    harness_proposal_view,
    list_harness_proposals,
    load_harness_proposal,
    render_harness_proposal_review,
)
from backend.application.kernel.harness_snapshots import write_harness_files

FIXED_TIME = "2026-10-21T00:00:00Z"
EVIDENCE_ID = "ev-tool-errors-001"


def _write_root(tmp_path: Path) -> Path:
    root = tmp_path / "harness"
    specs = [
        HarnessFileSpec(
            "system.md",
            "be helpful\n",
            component="system",
            provenance="test:system",
            owner="sage-builtin",
        ),
        HarnessFileSpec(
            "plugins.yaml",
            "harness_config:\n  preset: standard\n",
            component="plugins",
            provenance="test:plugins",
            owner="sage-builtin",
            authority="configuration",
        ),
        HarnessFileSpec(
            "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo skill\n---\n\nDemo\n",
            component="skills",
            provenance="test:skill",
            owner="workspace",
        ),
    ]
    write_harness_files(root, specs, generated_at=FIXED_TIME)
    return root


def _evidence(root: Path):
    return create_harness_evidence(
        root,
        EVIDENCE_ID,
        "tool_trajectory",
        {"session_id": "session-1", "tool": "bash", "signature": "bash:command"},
        excerpt="bash failed twice because the working directory drifted; retry wasted a turn.",
        metrics={"tool_error_rate": 0.2},
        created_at=FIXED_TIME,
    )


def _candidate(candidate_id: str, content: str, evidence_ids=None):
    return {
        "id": candidate_id,
        "lane": candidate_id,
        "summary": candidate_id + " candidate",
        "edits": [
            {
                "path": "system.md",
                "operation": "write",
                "content": content,
                "evidence_ids": list([EVIDENCE_ID] if evidence_ids is None else evidence_ids),
                "rationale": "tool trajectory shows repeated avoidable failures",
            }
        ],
    }


def _create(root: Path, proposal_id: str = "prop-system-001", candidates=None):
    return create_harness_proposal(
        root,
        title="Reduce repeated tool failures",
        summary="Anchor system guidance to a verified working directory.",
        candidates=candidates
        or [
            _candidate("invariant", "be helpful\nverify cwd first\n"),
            _candidate("domain", "be helpful\nverify repo cwd first\n"),
        ],
        author="tester",
        proposal_id=proposal_id,
        created_at=FIXED_TIME,
    )


def _probe_report(candidates: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "dataset": {"id": "replay-001", "evidence_ids": [EVIDENCE_ID]},
        "base_metrics": {"tool_error_rate": 0.2, "success_rate": 0.7},
        "candidates": candidates,
    }


def _candidate_probe(metrics, supported=True, path="system.md"):
    return {
        "metrics": metrics,
        "edits": {path: {"supported": supported, "evidence_ids": [EVIDENCE_ID]}},
    }


def test_evidence_hash_and_trajectory_gate(tmp_path: Path) -> None:
    root = _write_root(tmp_path)
    record = _evidence(root)
    assert load_harness_evidence(root, EVIDENCE_ID).evidence_sha256 == record.evidence_sha256

    evidence_file = root / "evidence" / (EVIDENCE_ID + ".json")
    original = evidence_file.read_text(encoding="utf-8")
    raw = json.loads(original)
    raw["excerpt"] = "tampered"
    evidence_file.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(HarnessFilesError, match="excerpt hash mismatch"):
        load_harness_evidence(root, EVIDENCE_ID)
    evidence_file.write_text(original, encoding="utf-8")
    create_harness_evidence(
        root,
        "metric-only-001",
        "metric_snapshot",
        {"dataset_id": "replay-001"},
        metrics={"tool_error_rate": 0.2},
        created_at=FIXED_TIME,
        overwrite=True,
    )
    with pytest.raises(HarnessFilesError, match="trajectory evidence"):
        _create(
            root,
            "prop-metric-only",
            [_candidate("invariant", "changed\n", ["metric-only-001"])],
        )
    assert not (root / "proposals" / "prop-metric-only").exists()

    with pytest.raises(HarnessFilesError, match="requires evidence"):
        _create(
            root,
            "prop-no-evidence",
            [_candidate("invariant", "changed\n", [])],
        )
    assert not (root / "proposals" / "prop-no-evidence").exists()


def test_create_anchors_candidates_without_mutating_harness(tmp_path: Path) -> None:
    root = _write_root(tmp_path)
    _evidence(root)
    base_lock = load_harness_lock(root)
    assert base_lock is not None

    proposal = _create(root)

    assert proposal.status == "draft"
    assert proposal.component == "system"
    assert proposal.base_lock_content_sha256 == base_lock.content_sha256
    assert (root / "system.md").read_text(encoding="utf-8") == "be helpful\n"
    assert verify_harness_files(root).valid is True
    candidate_file = (
        root
        / "proposals"
        / proposal.proposal_id
        / "candidates"
        / "domain"
        / "files"
        / "system.md"
    )
    assert candidate_file.read_text(encoding="utf-8").endswith("repo cwd first\n")
    view = harness_proposal_view(root, proposal.proposal_id)
    assert view["base_current"] is True
    assert view["evidence"][0]["valid"] is True
    assert [item.proposal_id for item in list_harness_proposals(root)] == [
        proposal.proposal_id
    ]

    multi = _candidate("invariant", "changed\n")
    multi["edits"].append(
        {
            "path": "plugins.yaml",
            "operation": "write",
            "content": "harness_config:\n  preset: focus\n",
            "evidence_ids": [EVIDENCE_ID],
        }
    )
    with pytest.raises(HarnessFilesError, match="exactly one harness component"):
        _create(root, "prop-multi-component", [multi])


def test_probe_compose_rejects_regression_and_selects_best_conflict(
    tmp_path: Path,
) -> None:
    root = _write_root(tmp_path)
    _evidence(root)
    proposal = _create(
        root,
        candidates=[
            _candidate("invariant", "be helpful\nverify cwd first\n"),
            _candidate("domain", "be helpful\nverify repo cwd first\n"),
            _candidate("regressed", "be helpful\nnever verify cwd\n"),
        ],
    )
    record_harness_probe(
        root,
        proposal.proposal_id,
        _probe_report(
            {
                "invariant": _candidate_probe(
                    {"tool_error_rate": 0.1, "success_rate": 0.8}
                ),
                "domain": _candidate_probe(
                    {"tool_error_rate": 0.05, "success_rate": 0.85}
                ),
                "regressed": _candidate_probe(
                    {"tool_error_rate": 0.3, "success_rate": 0.9}
                ),
            }
        ),
        recorded_at=FIXED_TIME,
    )

    composed = compose_harness_proposal(root, proposal.proposal_id, composed_at=FIXED_TIME)

    assert composed.status == "pending"
    assert [item.candidate_id for item in composed.selected_edits] == ["domain"]
    reasons = {
        (item["candidate_id"], item["reason"]) for item in composed.compose["discarded"]
    }
    assert ("regressed", "candidate_ineligible") in reasons
    assert ("invariant", "conflict_lost") in reasons
    review = render_harness_proposal_review(root, proposal.proposal_id)
    assert "bash failed twice" in review
    assert "+verify repo cwd first" in review


def test_compose_failed_when_probe_does_not_support_edit(tmp_path: Path) -> None:
    root = _write_root(tmp_path)
    _evidence(root)
    proposal = _create(root, candidates=[_candidate("invariant", "changed\n")])
    record_harness_probe(
        root,
        proposal.proposal_id,
        _probe_report(
            {
                "invariant": _candidate_probe(
                    {"tool_error_rate": 0.1, "success_rate": 0.8}, supported=False
                )
            }
        ),
    )

    with pytest.raises(HarnessFilesError, match="no evidence-supported edits"):
        compose_harness_proposal(root, proposal.proposal_id)
    assert load_harness_proposal(root, proposal.proposal_id).status == "compose_failed"


def _pending(root: Path, proposal_id: str, candidates=None):
    proposal = _create(root, proposal_id, candidates)
    report_candidates = {}
    for candidate in proposal.candidates:
        edits = {
            edit.path: {"supported": True, "evidence_ids": [EVIDENCE_ID]}
            for edit in candidate.edits
        }
        report_candidates[candidate.candidate_id] = {
            "metrics": {"tool_error_rate": 0.1, "success_rate": 0.8},
            "edits": edits,
        }
    record_harness_probe(root, proposal_id, _probe_report(report_candidates))
    # Tie conflicts are intentionally discarded; lifecycle tests use one candidate
    # unless the caller supplies a single-candidate list.
    return compose_harness_proposal(root, proposal_id)


def test_approve_adopt_and_rollback_restore_base(tmp_path: Path) -> None:
    root = _write_root(tmp_path)
    _evidence(root)
    proposal = _pending(
        root,
        "prop-adopt-001",
        [_candidate("invariant", "be helpful\nadopted guidance\n")],
    )

    approve_harness_proposal(root, proposal.proposal_id, actor="reviewer")
    result = adopt_harness_proposal(root, proposal.proposal_id, actor="reviewer")

    assert result["changed_files"] == ["system.md"]
    assert result["pre_snapshot"]["id"].startswith("pre-proposal-")
    assert (root / "system.md").read_text(encoding="utf-8").endswith("adopted guidance\n")
    assert verify_harness_files(root).valid is True
    assert load_harness_proposal(root, proposal.proposal_id).status == "adopted"

    rollback_harness_proposal(root, proposal.proposal_id)
    assert (root / "system.md").read_text(encoding="utf-8") == "be helpful\n"
    assert verify_harness_files(root).valid is True
    assert load_harness_proposal(root, proposal.proposal_id).status == "rolled_back"


def test_stale_base_and_post_adoption_drift_are_explicit(tmp_path: Path) -> None:
    root = _write_root(tmp_path)
    _evidence(root)
    stale = _pending(
        root,
        "prop-stale-001",
        [_candidate("invariant", "be helpful\nstale candidate\n")],
    )
    (root / "system.md").write_text("drifted\n", encoding="utf-8")
    with pytest.raises(HarnessFilesError):
        approve_harness_proposal(root, stale.proposal_id)
    assert load_harness_proposal(root, stale.proposal_id).status == "stale"

    rollback_harness_files = __import__(
        "backend.application.kernel.harness_snapshots",
        fromlist=["rollback_harness_files"],
    ).rollback_harness_files
    rollback_harness_files(root, "initial", create_pre_snapshot=False)
    adopted = _pending(
        root,
        "prop-drift-001",
        [_candidate("invariant", "be helpful\nadopted then drift\n")],
    )
    approve_harness_proposal(root, adopted.proposal_id)
    adopt_harness_proposal(root, adopted.proposal_id)
    (root / "plugins.yaml").write_text(
        "harness_config:\n  preset: focus\n", encoding="utf-8"
    )
    from backend.application.kernel.harness_files import update_harness_lock

    update_harness_lock(root)
    with pytest.raises(HarnessFilesError, match="requires force"):
        rollback_harness_proposal(root, adopted.proposal_id)
    rollback_harness_proposal(root, adopted.proposal_id, force=True)
    assert (root / "system.md").read_text(encoding="utf-8") == "be helpful\n"
    assert "standard" in (root / "plugins.yaml").read_text(encoding="utf-8")


def test_add_delete_and_candidate_staging(tmp_path: Path) -> None:
    root = _write_root(tmp_path)
    _evidence(root)
    candidate = {
        "id": "domain",
        "lane": "domain",
        "edits": [
            {
                "path": "skills/new/SKILL.md",
                "operation": "write",
                "content": "---\nname: new\ndescription: New skill\n---\n\nNew\n",
                "evidence_ids": [EVIDENCE_ID],
            },
            {
                "path": "skills/demo/SKILL.md",
                "operation": "delete",
                "evidence_ids": [EVIDENCE_ID],
            },
        ],
    }
    proposal = create_harness_proposal(
        root,
        title="Replace demo skill",
        summary="Evidence shows the demo guidance caused repeated failures.",
        candidates=[candidate],
        author="tester",
        proposal_id="prop-skills-001",
        created_at=FIXED_TIME,
    )
    staged = tmp_path / "staged"
    result = stage_harness_candidate(root, proposal.proposal_id, "domain", staged)
    assert result["file_count"] == 3
    assert (staged / "skills" / "new" / "SKILL.md").exists()
    assert not (staged / "skills" / "demo" / "SKILL.md").exists()
    assert verify_harness_files(staged).valid is True
    assert verify_harness_files(root).valid is True

    report = _probe_report(
        {
            "domain": {
                "metrics": {"tool_error_rate": 0.1, "success_rate": 0.8},
                "edits": {
                    "skills/new/SKILL.md": {
                        "supported": True,
                        "evidence_ids": [EVIDENCE_ID],
                    },
                    "skills/demo/SKILL.md": {
                        "supported": True,
                        "evidence_ids": [EVIDENCE_ID],
                    },
                },
            }
        }
    )
    record_harness_probe(root, proposal.proposal_id, report)
    compose_harness_proposal(root, proposal.proposal_id)
    approve_harness_proposal(root, proposal.proposal_id)
    adopt_harness_proposal(root, proposal.proposal_id)
    assert (root / "skills" / "new" / "SKILL.md").exists()
    assert not (root / "skills" / "demo" / "SKILL.md").exists()
    rollback_harness_proposal(root, proposal.proposal_id)
    assert not (root / "skills" / "new" / "SKILL.md").exists()
    assert (root / "skills" / "demo" / "SKILL.md").exists()
