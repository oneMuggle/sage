"""Unit tests for deterministic playbook auditing and stage detection (2026-10-31)."""

from __future__ import annotations

from pathlib import Path

from backend.services.playbook_auditor import audit_playbook, match_glob
from backend.services.playbook_library import get_builtin


def _project(path: Path) -> dict:
    return {"id": "p1", "name": "demo", "path": str(path)}


def _make_research_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    proposal = root / "01_开题"
    proposal.mkdir()
    (proposal / "开题报告.md").write_text(
        "研究问题\n科学假设\n技术路线", encoding="utf-8"
    )
    return root


def test_glob_supports_braces_and_double_star(tmp_path: Path) -> None:
    root = tmp_path / "g"
    (root / "02_实施" / "数据" / "raw").mkdir(parents=True)
    target = root / "02_实施" / "数据" / "raw" / "sample.csv"
    target.write_text("a,b\n1,2\n", encoding="utf-8")
    nested = root / "docs" / "deep"
    nested.mkdir(parents=True)
    (nested / "note.md").write_text("x", encoding="utf-8")
    (root / "docs" / "top.md").write_text("x", encoding="utf-8")

    data_matches = match_glob(root, "02_实施/数据/**/*.{csv,json}")
    assert [path.name for path in data_matches] == ["sample.csv"]

    assert [path.name for path in match_glob(root, "docs/*.md")] == ["top.md"]
    assert {path.name for path in match_glob(root, "**/*.{md,docx}")} == {
        "note.md",
        "top.md",
    }


def test_glob_ignores_excluded_dirs(tmp_path: Path) -> None:
    root = tmp_path / "g2"
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "a.md").write_text("x", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "b.md").write_text("x", encoding="utf-8")
    assert match_glob(root, "**/*.md") == []


def test_required_and_optional_artifacts(tmp_path: Path) -> None:
    root = _make_research_project(tmp_path)
    result = audit_playbook(_project(root), get_builtin("cn-research-grant"))
    proposal = next(stage for stage in result["stages"] if stage["id"] == "proposal")
    report = next(item for item in proposal["artifacts"] if item["id"] == "proposal_report")
    assert report["status"] == "present"
    ethics = next(item for item in proposal["artifacts"] if item["id"] == "ethics_approval")
    assert ethics["status"] == "optional"
    literature = next(
        item for item in proposal["artifacts"] if item["id"] == "literature_matrix"
    )
    assert literature["status"] == "optional"


def test_overall_progress_and_detected_stage(tmp_path: Path) -> None:
    root = _make_research_project(tmp_path)
    result = audit_playbook(_project(root), get_builtin("cn-research-grant"))
    assert 0 < result["overall"]["progress"] < 100
    assert result["overall"]["required_done"] >= 1
    assert result["detected_stage"]["id"] in {"proposal", "execution", "closure"}
    assert "evidence" in result["detected_stage"]


def test_manual_waiver_counts_as_done(tmp_path: Path) -> None:
    root = _make_research_project(tmp_path)
    spec = get_builtin("cn-research-grant")
    state = {"waivers": ["closure.final_report"]}
    result = audit_playbook(_project(root), spec, state=state)
    closure = next(stage for stage in result["stages"] if stage["id"] == "closure")
    report = next(item for item in closure["artifacts"] if item["id"] == "final_report")
    assert report["status"] == "waived"


def test_path_outside_root_is_not_scanned(tmp_path: Path) -> None:
    root = _make_research_project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "开题报告.md").write_text("研究问题", encoding="utf-8")
    result = audit_playbook(_project(root), get_builtin("cn-research-grant"))
    proposal = next(stage for stage in result["stages"] if stage["id"] == "proposal")
    report = next(item for item in proposal["artifacts"] if item["id"] == "proposal_report")
    assert report["evidence"]["matches"] == ["01_开题/开题报告.md"]


def test_classification_suggestion_for_misplaced_file(tmp_path: Path) -> None:
    root = tmp_path / "misplaced"
    root.mkdir()
    (root / "开题报告.md").write_text("研究问题\n假设\n技术路线", encoding="utf-8")
    result = audit_playbook(_project(root), get_builtin("cn-research-grant"))
    suggestions = result["classification_suggestions"]
    assert any(
        item["from"] == "开题报告.md" and item["to"] == "01_开题/开题报告.md"
        for item in suggestions
    )


def test_required_when_condition_controls_required(tmp_path: Path) -> None:
    root = _make_research_project(tmp_path)
    spec = get_builtin("cn-research-grant")
    result = audit_playbook(_project(root), spec)
    proposal = next(stage for stage in result["stages"] if stage["id"] == "proposal")
    ethics = next(item for item in proposal["artifacts"] if item["id"] == "ethics_approval")
    assert ethics["required"] is False
    assert ethics["status"] == "optional"

    enabled = audit_playbook(
        _project(root),
        spec,
        state={"conditions": {"contains_human_subjects": True}},
    )
    proposal = next(stage for stage in enabled["stages"] if stage["id"] == "proposal")
    ethics = next(item for item in proposal["artifacts"] if item["id"] == "ethics_approval")
    assert ethics["required"] is True
    assert ethics["status"] == "missing"


def test_unclassified_document_gets_destination_suggestion(tmp_path: Path) -> None:
    root = _make_research_project(tmp_path)
    (root / "论文初稿.docx").write_bytes(b"x" * 32)
    (root / "随手笔记.md").write_text("随手记录", encoding="utf-8")

    result = audit_playbook(_project(root), get_builtin("cn-research-grant"))
    by_path = {item["path"]: item for item in result["unclassified_files"]}

    assert by_path["论文初稿.docx"]["suggested_to"] == "03_成果/论文初稿.docx"
    assert by_path["论文初稿.docx"]["confidence"] >= 0.5
    assert "论文" in by_path["论文初稿.docx"]["reason"]
    # Files already matched by an artifact glob, or without a keyword signal,
    # must not be reported as unclassified.
    assert "01_开题/开题报告.md" not in by_path
    assert "随手笔记.md" not in by_path


def test_undo_available_reflects_last_batch_move(tmp_path: Path) -> None:
    root = _make_research_project(tmp_path)
    spec = get_builtin("cn-research-grant")
    plain = audit_playbook(_project(root), spec)
    assert plain["undo_available"] is None

    state = {
        "last_move_batch": {
            "at": 1793500000000,
            "moves": [{"from": "a.md", "to": "01_开题/a.md"}],
        }
    }
    with_batch = audit_playbook(_project(root), spec, state=state)
    assert with_batch["undo_available"] == {"at": 1793500000000, "count": 1}

