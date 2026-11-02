"""Tests for safe LaTeX project zip import."""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from backend.office.errors import OfficeParseError, OfficePathError
from backend.office.latex.project import extract_latex_project_zip


def _write_zip(
    path: Path,
    entries: dict,
    *,
    symlink: bool = False,
    compression: int = zipfile.ZIP_STORED,
) -> Path:
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for name, content in entries.items():
            if symlink and name == "link.tex":
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, content)
            else:
                archive.writestr(name, content)
    return path


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def test_extract_project_and_detect_main(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    archive = _write_zip(
        workspace / "paper.zip",
        {
            "paper/main.tex": "\\documentclass{article}",
            "paper/sections/intro.tex": "\\section{Intro}",
            "paper/figs/arch.png": b"png",
            "paper/notes.txt": "notes",
        },
    )

    result = extract_latex_project_zip(
        archive, workspace=workspace, output_dir_name="imported"
    )

    assert result["ok"] is True
    assert result["project_dir"] == "imported"
    assert result["main_file"] == "imported/paper/main.tex"
    assert result["files_count"] == 4
    assert (workspace / "imported" / "paper" / "main.tex").is_file()


def test_extract_rejects_path_traversal(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    archive = _write_zip(
        workspace / "bad.zip",
        {"../evil.tex": "\\documentclass{article}"},
    )

    with pytest.raises(OfficeParseError):
        extract_latex_project_zip(archive, workspace=workspace, output_dir_name="bad")

    assert not (tmp_path / "evil.tex").exists()


def test_extract_rejects_symlink(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    archive = _write_zip(
        workspace / "symlink.zip",
        {"link.tex": "target"},
        symlink=True,
    )

    with pytest.raises(OfficeParseError):
        extract_latex_project_zip(
            archive, workspace=workspace, output_dir_name="symlink"
        )


def test_extract_refuses_existing_output(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "existing").mkdir()
    archive = _write_zip(
        workspace / "paper.zip", {"main.tex": "\\documentclass{article}"}
    )

    with pytest.raises(OfficeParseError):
        extract_latex_project_zip(
            archive, workspace=workspace, output_dir_name="existing"
        )


def test_extract_without_main_warns(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    archive = _write_zip(workspace / "empty.zip", {"sections/intro.tex": "Hello"})

    result = extract_latex_project_zip(
        archive, workspace=workspace, output_dir_name="empty"
    )

    assert result["ok"] is True
    assert result["main_file"] is None
    assert any(w["code"] == "no_main_tex" for w in result["warnings"])


def test_extract_skips_unsupported_suffix(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    archive = _write_zip(
        workspace / "paper.zip",
        {
            "main.tex": "\\documentclass{article}",
            "run.sh": "echo hi",
        },
    )

    result = extract_latex_project_zip(
        archive, workspace=workspace, output_dir_name="paper"
    )

    assert result["files_count"] == 1
    assert any(w["code"] == "unsupported_file_skipped" for w in result["warnings"])
    assert not (workspace / "paper" / "run.sh").exists()


def test_extract_rejects_case_collision(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    archive = _write_zip(
        workspace / "paper.zip",
        {
            "Main.tex": "\\documentclass{article}",
            "main.tex": "\\documentclass{article}",
        },
    )

    with pytest.raises(OfficeParseError):
        extract_latex_project_zip(archive, workspace=workspace, output_dir_name="paper")


def test_extract_rejects_duplicate_entry(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    archive = workspace / "paper.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("main.tex", "\\documentclass{article}")
        handle.writestr("main.tex", "\\documentclass{book}")

    with pytest.raises(OfficeParseError):
        extract_latex_project_zip(archive, workspace=workspace, output_dir_name="paper")


def test_extract_rejects_windows_reserved_name(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    archive = _write_zip(
        workspace / "paper.zip",
        {"CON.tex": "\\documentclass{article}"},
    )

    with pytest.raises(OfficeParseError):
        extract_latex_project_zip(archive, workspace=workspace, output_dir_name="paper")


def test_extract_rejects_compression_bomb(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    archive = _write_zip(
        workspace / "bomb.zip",
        {"main.tex": b"\0" * (11 * 1024 * 1024)},
        compression=zipfile.ZIP_DEFLATED,
    )

    with pytest.raises(OfficeParseError):
        extract_latex_project_zip(archive, workspace=workspace, output_dir_name="bomb")


def test_extract_rejects_zip_outside_workspace(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    outside = _write_zip(
        tmp_path / "outside.zip", {"main.tex": "\\documentclass{article}"}
    )

    with pytest.raises(OfficePathError):
        extract_latex_project_zip(
            outside, workspace=workspace, output_dir_name="outside"
        )

    assert not (workspace / "outside").exists()
