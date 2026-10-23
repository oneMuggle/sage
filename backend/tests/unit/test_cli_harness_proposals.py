# ruff: noqa: UP006, UP007, UP035
"""R85 ``harness proposals`` CLI 契约。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterator

import pytest

from backend.application.kernel.harness_config import clear_harness_cache
from backend.application.kernel.harness_evidence import create_harness_evidence
from backend.application.kernel.harness_files import HarnessFileSpec
from backend.application.kernel.harness_proposals import (
    create_harness_proposal,
    load_harness_proposal,
)
from backend.application.kernel.harness_snapshots import write_harness_files
from backend.cli.harness import main

FIXED_TIME = "2026-10-21T00:00:00Z"
EVIDENCE_ID = "ev-tool-errors-001"


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in (
        "SAGE_HARNESS_PRESET",
        "SAGE_HARNESS_HOME",
        "SAGE_WORKSPACE",
        "SAGE_HARNESS_LOCK_ENFORCE",
    ):
        monkeypatch.delenv(name, raising=False)
    clear_harness_cache()
    yield
    clear_harness_cache()


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "harness"
    write_harness_files(
        root,
        [
            HarnessFileSpec("system.md", "be helpful\n", component="system"),
            HarnessFileSpec(
                "plugins.yaml",
                "harness_config:\n  preset: standard\n",
                component="plugins",
                authority="configuration",
            ),
        ],
        generated_at=FIXED_TIME,
    )
    return root


def _write_json(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _evidence_payload():
    return {
        "id": EVIDENCE_ID,
        "evidence_kind": "tool_trajectory",
        "source": {"session_id": "session-1", "tool": "bash"},
        "excerpt": "bash failed after cwd drift and wasted a retry.",
        "metrics": {"tool_error_rate": 0.2},
        "created_at": FIXED_TIME,
    }


def _probe_payload(path="system.md", candidate="invariant"):
    return {
        "dataset": {"id": "replay-001", "evidence_ids": [EVIDENCE_ID]},
        "base_metrics": {"tool_error_rate": 0.2, "success_rate": 0.7},
        "candidates": {
            candidate: {
                "metrics": {"tool_error_rate": 0.1, "success_rate": 0.8},
                "edits": {
                    path: {"supported": True, "evidence_ids": [EVIDENCE_ID]}
                },
            }
        },
    }


def test_proposals_cli_full_lifecycle_and_submit(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    root = _root(tmp_path)
    evidence_file = _write_json(tmp_path / "evidence.json", _evidence_payload())
    assert (
        main(
            [
                "proposals",
                "evidence-add",
                "--output",
                str(root),
                "--input",
                str(evidence_file),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["id"] == EVIDENCE_ID

    (tmp_path / "candidate-system.txt").write_text(
        "be helpful\nverify cwd first\n", encoding="utf-8"
    )
    proposal_file = _write_json(
        tmp_path / "proposal.json",
        {
            "id": "prop-cli-001",
            "title": "Verify cwd",
            "summary": "Trajectory shows cwd drift caused retries.",
            "author": "tester",
            "created_at": FIXED_TIME,
            "candidates": [
                {
                    "id": "invariant",
                    "lane": "invariant",
                    "edits": [
                        {
                            "path": "system.md",
                            "content_file": "candidate-system.txt",
                            "evidence_ids": [EVIDENCE_ID],
                        }
                    ],
                }
            ],
        },
    )
    assert (
        main(
            [
                "proposals",
                "create",
                "--output",
                str(root),
                "--input",
                str(proposal_file),
                "--json",
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    assert created["status"] == "draft"

    probe_file = _write_json(tmp_path / "probe.json", _probe_payload())
    assert (
        main(
            [
                "proposals",
                "probe",
                "--output",
                str(root),
                "prop-cli-001",
                "--report",
                str(probe_file),
                "--static",
                "--compose",
                "--json",
            ]
        )
        == 0
    )
    probed = json.loads(capsys.readouterr().out)
    assert probed["proposal"]["status"] == "pending"
    assert probed["static"]["candidates"]["invariant"] == []

    assert main(["proposals", "validate", "--output", str(root), "prop-cli-001"]) == 0
    assert "valid: True" in capsys.readouterr().out
    assert (
        main(
            [
                "proposals",
                "show",
                "--output",
                str(root),
                "prop-cli-001",
                "--patch",
            ]
        )
        == 0
    )
    review = capsys.readouterr().out
    assert "+verify cwd first" in review
    assert "bash failed after cwd drift" in review

    db_path = tmp_path / "drafts.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE skill_drafts (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
                when_to_use TEXT NOT NULL, content TEXT NOT NULL,
                trigger_type TEXT NOT NULL, source_session_id TEXT,
                source_context TEXT, status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL, reviewed_at INTEGER,
                reviewed_by_user_id TEXT
            )
            """
        )
    assert (
        main(
            [
                "proposals",
                "submit",
                "--output",
                str(root),
                "prop-cli-001",
                "--db-path",
                str(db_path),
                "--json",
            ]
        )
        == 0
    )
    submitted = json.loads(capsys.readouterr().out)
    assert submitted["trigger_type"] == "harness_proposal"
    assert submitted["source_context"]["proposal_id"] == "prop-cli-001"

    assert main(["proposals", "approve", "--output", str(root), "prop-cli-001"]) == 0
    capsys.readouterr()
    assert main(["proposals", "adopt", "--output", str(root), "prop-cli-001"]) == 0
    capsys.readouterr()
    assert "verify cwd first" in (root / "system.md").read_text(encoding="utf-8")
    assert main(["proposals", "rollback", "--output", str(root), "prop-cli-001"]) == 0
    capsys.readouterr()
    assert (root / "system.md").read_text(encoding="utf-8") == "be helpful\n"


def test_proposals_cli_static_probe_eliminates_invalid_yaml(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    root = _root(tmp_path)
    create_harness_evidence(
        root,
        EVIDENCE_ID,
        "tool_trajectory",
        {"session_id": "session-1", "tool": "bash"},
        excerpt="tool trajectory",
        created_at=FIXED_TIME,
    )
    create_harness_proposal(
        root,
        title="Broken plugins candidate",
        summary="Static probe must reject invalid YAML.",
        candidates=[
            {
                "id": "invariant",
                "lane": "invariant",
                "edits": [
                    {
                        "path": "plugins.yaml",
                        "content": "harness_config:\n  preset: [broken\n",
                        "evidence_ids": [EVIDENCE_ID],
                    }
                ],
            }
        ],
        proposal_id="prop-cli-static",
        created_at=FIXED_TIME,
    )
    probe_file = _write_json(
        tmp_path / "probe.json", _probe_payload(path="plugins.yaml")
    )

    assert (
        main(
            [
                "proposals",
                "probe",
                "--output",
                str(root),
                "prop-cli-static",
                "--report",
                str(probe_file),
                "--static",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["static"]["candidates"]["invariant"]
    assert payload["proposal"]["probe"]["report"]["candidates"]["invariant"]["metrics"][
        "static_errors"
    ] >= 1
    assert main(["proposals", "compose", "--output", str(root), "prop-cli-static"]) == 1
    assert "no evidence-supported edits" in capsys.readouterr().err
    assert load_harness_proposal(root, "prop-cli-static").status == "compose_failed"


def test_proposals_cli_generate_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    root = _root(tmp_path)
    create_harness_evidence(
        root,
        EVIDENCE_ID,
        "tool_trajectory",
        {"session_id": "session-1", "tool": "bash"},
        excerpt="tool trajectory",
        created_at=FIXED_TIME,
    )

    class FakeService:
        async def generate(self, harness_root, **kwargs):
            return create_harness_proposal(
                harness_root,
                title="Generated by fake service",
                summary="Evidence anchored generated candidates.",
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
                    },
                    {
                        "id": "domain",
                        "lane": "domain",
                        "edits": [
                            {
                                "path": "plugins.yaml",
                                "content": "harness_config:\n  preset: dev\n",
                                "evidence_ids": [EVIDENCE_ID],
                            }
                        ],
                    },
                ],
                proposal_id=kwargs["proposal_id"],
                created_at=FIXED_TIME,
            )

    monkeypatch.setattr(
        "backend.skills.harness_proposal_service.get_harness_proposal_service",
        lambda: FakeService(),
    )
    assert (
        main(
            [
                "proposals",
                "generate",
                "--output",
                str(root),
                "--path",
                "plugins.yaml",
                "--goal",
                "focus tools",
                "--evidence",
                EVIDENCE_ID,
                "--proposal-id",
                "prop-cli-generated",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "draft"
    assert [item["lane"] for item in payload["candidates"]] == ["invariant", "domain"]
