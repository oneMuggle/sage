"""Service-boundary tests for the LaTeX preview reader."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.office.errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficePathError,
    OfficeSizeLimitError,
)
from backend.office.latex.service import read_latex_file


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def test_read_latex_file_rejects_oversize(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = workspace / "big.tex"
    source.write_text("x" * 100, encoding="utf-8")

    with pytest.raises(OfficeSizeLimitError):
        read_latex_file(source, workspace=workspace, max_bytes=10)


def test_read_latex_file_rejects_outside_workspace(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    outside = tmp_path / "outside.tex"
    outside.write_text("\\documentclass{article}", encoding="utf-8")

    with pytest.raises(OfficePathError):
        read_latex_file(outside, workspace=workspace)


def test_read_latex_file_missing_file(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    with pytest.raises(OfficeFileNotFoundError):
        read_latex_file(workspace / "missing.tex", workspace=workspace)


def test_read_latex_file_rejects_non_tex_suffix(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = workspace / "notes.md"
    source.write_text("# notes", encoding="utf-8")

    with pytest.raises(OfficeParseError):
        read_latex_file(source, workspace=workspace)
