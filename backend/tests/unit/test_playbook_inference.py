"""Unit tests for playbook stage inference (2026-11-14)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend.services import playbook_inference
from backend.services.playbook_inference import (
    infer_from_directory,
    infer_from_git_history,
    infer_project_stages,
    inferred_spec,
)


def _project(path: str) -> SimpleNamespace:
    return SimpleNamespace(id="proj-1", name="示例课题", path=path)


def test_directory_numbered_dirs_become_stages(tmp_path: Path) -> None:
    (tmp_path / "01_开题").mkdir()
    (tmp_path / "01_开题" / "开题报告.md").write_text("x", encoding="utf-8")
    (tmp_path / "2-实施").mkdir()
    (tmp_path / "2-实施" / "实施方案.docx").write_text("x", encoding="utf-8")
    (tmp_path / "03_数据采集").mkdir()

    result = infer_from_directory(str(tmp_path))
    assert result.source == "directory"
    assert result.confidence == 0.8
    assert [stage.label for stage in result.stages] == ["开题", "实施", "数据采集"]
    assert result.stages[0].artifacts == ["开题报告"]
    assert result.stages[1].artifacts == ["实施方案"]


def test_directory_plain_dirs_low_confidence(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "src").mkdir()
    result = infer_from_directory(str(tmp_path))
    assert result.stages == []
    assert result.confidence == 0.2


def test_directory_missing_path(tmp_path: Path) -> None:
    result = infer_from_directory(str(tmp_path / "missing"))
    assert result.stages == []
    assert result.confidence == 0.0


def test_git_history_buckets_keywords(tmp_path: Path, monkeypatch) -> None:
    class Completed:
        returncode = 0
        stdout = "feat: 完成开题报告\nfix: 修复测试用例\nchore: 环境配置\n"

    monkeypatch.setattr(
        playbook_inference.subprocess, "run", lambda *args, **kwargs: Completed()
    )
    result = infer_from_git_history(str(tmp_path))
    assert result.source == "git"
    labels = [stage.label for stage in result.stages]
    assert labels[0] == "开题"
    assert "测试" in labels
    assert result.confidence > 0


def test_git_history_not_repo(tmp_path: Path) -> None:
    result = infer_from_git_history(str(tmp_path))
    assert result.source == "git"
    assert result.stages == []
    assert result.confidence == 0.0


def test_infer_project_stages_prefers_directory(tmp_path: Path) -> None:
    (tmp_path / "01_开题").mkdir()
    (tmp_path / "02_实施").mkdir()
    result = infer_project_stages(_project(str(tmp_path)))
    assert result.source == "directory"
    assert [stage.label for stage in result.stages] == ["开题", "实施"]


def test_inferred_spec_shape(tmp_path: Path) -> None:
    (tmp_path / "01_开题").mkdir()
    (tmp_path / "01_开题" / "开题报告.md").write_text("x", encoding="utf-8")
    (tmp_path / "02_实施").mkdir()
    spec = inferred_spec(_project(str(tmp_path)))
    assert spec is not None
    assert spec["id"] == "inferred-proj-1"
    assert spec["name"] == "示例课题 规程（推断）"
    assert [stage["id"] for stage in spec["stages"]] == ["stage-1", "stage-2"]
    assert spec["stages"][0]["artifacts"][0]["match"]["globs"] == ["**/开题报告*"]


def test_inferred_spec_none_when_no_stages(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    assert inferred_spec(_project(str(tmp_path))) is None
