"""Tests for latexdiff adapter (stubbed tool)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.office.errors import OfficeParseError
from backend.office.latex import diff as diff_mod
from backend.office.latex.diff import latexdiff_files


def _workspace(tmp_path: Path) -> tuple:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    original = workspace / "v1.tex"
    revised = workspace / "v2.tex"
    original.write_text("\\documentclass{article}\\begin{document}A\\end{document}")
    revised.write_text("\\documentclass{article}\\begin{document}B\\end{document}")
    return workspace, original, revised


def test_latexdiff_missing_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, original, revised = _workspace(tmp_path)
    monkeypatch.setattr(diff_mod.shutil, "which", lambda name: None)

    result = latexdiff_files(original, revised, root=workspace)

    assert result["ok"] is False
    assert result["code"] == "no_latexdiff"


def test_latexdiff_writes_diff_tex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, original, revised = _workspace(tmp_path)
    monkeypatch.setattr(
        diff_mod.shutil,
        "which",
        lambda name: "/usr/bin/latexdiff" if name == "latexdiff" else None,
    )
    calls = []

    def fake_run(cmd, cwd, shell, timeout, capture_output, text, check=None):
        calls.append({"cmd": cmd, "cwd": cwd})
        return subprocess.CompletedProcess(
            cmd, 0, "\\documentclass{article}\\DIFadd{B}", ""
        )

    monkeypatch.setattr(diff_mod.subprocess, "run", fake_run)

    result = latexdiff_files(
        original,
        revised,
        root=workspace,
        output_filename="diff.tex",
    )

    assert result["ok"] is True
    assert result["diff_path"] == "diff.tex"
    assert (workspace / "diff.tex").read_text(encoding="utf-8").startswith(
        "\\documentclass"
    )
    assert calls
    assert calls[0]["cmd"][0] == "/usr/bin/latexdiff"


def test_latexdiff_refuses_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, original, revised = _workspace(tmp_path)
    (workspace / "diff.tex").write_text("existing")
    monkeypatch.setattr(
        diff_mod.shutil,
        "which",
        lambda name: "/usr/bin/latexdiff" if name == "latexdiff" else None,
    )

    with pytest.raises(OfficeParseError):
        latexdiff_files(original, revised, root=workspace, output_filename="diff.tex")
