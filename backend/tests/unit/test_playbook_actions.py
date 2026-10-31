"""Unit tests for playbook action execution (2026-10-31)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.data import database as database_module
from backend.data.database import Database
from backend.data.playbook_repo import PlaybookRepository
from backend.data.project_repo import ProjectRepository
from backend.services.playbook_actions import apply_playbook_actions


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return test_db


@pytest.fixture()
def project(db: Database, tmp_path: Path):
    root = tmp_path / "demo"
    root.mkdir()
    return ProjectRepository().register(str(root), project_type="research")


def test_create_folder_and_doc_stub_idempotent(project, tmp_path: Path) -> None:
    result = apply_playbook_actions(
        project,
        [
            {"type": "create_folder", "payload": {"path": "01_开题"}},
            {
                "type": "create_doc_stub",
                "payload": {"path": "01_开题/开题报告.md", "template": "research_proposal"},
            },
        ],
    )
    assert "create_folder" in result["applied"]
    assert "create_doc_stub" in result["applied"]
    stub = tmp_path / "demo" / "01_开题" / "开题报告.md"
    assert stub.is_file()
    text = stub.read_text(encoding="utf-8")
    assert "研究背景" in text or "研究问题" in text

    again = apply_playbook_actions(
        project,
        [
            {"type": "create_folder", "payload": {"path": "01_开题"}},
            {
                "type": "create_doc_stub",
                "payload": {"path": "01_开题/开题报告.md", "template": "research_proposal"},
            },
        ],
    )
    assert "create_folder" in again["skipped"]
    assert "create_doc_stub" in again["skipped"]


def test_apply_rules_and_milestones_dedup(project) -> None:
    actions = [
        {
            "type": "apply_rules",
            "payload": {
                "rules": [
                    {"content": "Use ruff", "category": "coding_style", "priority": 7}
                ]
            },
        },
        {
            "type": "seed_milestones",
            "payload": {
                "milestones": [{"title": "开题报告", "stage": "proposal"}]
            },
        },
    ]
    first = apply_playbook_actions(project, actions)
    second = apply_playbook_actions(project, actions)
    assert "apply_rules" in first["applied"]
    assert "seed_milestones" in first["applied"]
    assert "apply_rules" in second["skipped"]
    assert "seed_milestones" in second["skipped"]


def test_rejects_path_escape(project) -> None:
    result = apply_playbook_actions(
        project,
        [{"type": "create_folder", "payload": {"path": "../escape"}}],
    )
    assert result["errors"]
    assert not (Path(project.path).parent / "escape").exists()


def test_set_stage_records_history(project) -> None:
    result = apply_playbook_actions(
        project, [{"type": "set_stage", "payload": {"stage_id": "execution"}}]
    )
    assert "set_stage" in result["applied"]
    updated = ProjectRepository().get(project.id)
    assert updated is not None
    assert updated.project_stage == "execution"
    state = PlaybookRepository().get_state(project.id)
    assert state["current_stage"] == "execution"
    assert state["stage_history"][-1]["to"] == "execution"


def test_unknown_action_reports_error(project) -> None:
    result = apply_playbook_actions(project, [{"type": "rm_rf", "payload": {}}])
    assert result["errors"]
    assert "rm_rf" in result["errors"][0]["item"]
