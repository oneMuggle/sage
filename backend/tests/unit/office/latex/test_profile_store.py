"""Tests for the workspace compliance profile library."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.office.errors import OfficeFileNotFoundError, OfficeParseError
from backend.office.latex.profile_store import (
    delete_latex_profile,
    list_latex_profiles,
    load_latex_profile,
    save_latex_profile,
)

_PROFILE = {
    "required_sections": ["Introduction", "Conclusion"],
    "required_metadata": ["title", "abstract"],
    "allowed_page_sizes": ["A4"],
    "required_min_pages": 8,
    "required_max_pages": 20,
    "require_embedded_fonts": True,
    "min_image_dpi": 300,
    "forbidden_commands": ["write18"],
}


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def test_save_list_load_delete_roundtrip(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    saved = save_latex_profile(
        workspace,
        "ieee-2026",
        _PROFILE,
        source="guidelines.pdf",
        evidence=[{"field": "required_max_pages", "value": 20}],
    )

    assert saved["name"] == "ieee-2026"
    assert saved["updated_at"]
    assert saved["profile"]["required_max_pages"] == 20
    stored = workspace / ".sage" / "latex-profiles" / "ieee-2026.json"
    assert stored.is_file()

    listed = list_latex_profiles(workspace)
    assert [item["name"] for item in listed["profiles"]] == ["ieee-2026"]

    loaded = load_latex_profile(workspace, "ieee-2026")
    assert loaded["profile"]["min_image_dpi"] == 300
    assert loaded["source"] == "guidelines.pdf"

    deleted = delete_latex_profile(workspace, "ieee-2026")
    assert deleted["ok"] is True
    assert not stored.exists()


def test_load_missing_profile_raises(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    with pytest.raises(OfficeFileNotFoundError):
        load_latex_profile(workspace, "missing")


def test_rejects_invalid_name(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    with pytest.raises(OfficeParseError):
        save_latex_profile(workspace, "../evil", _PROFILE)

    assert not (tmp_path / "evil.json").exists()


def test_save_normalizes_profile(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    saved = save_latex_profile(
        workspace,
        "normalized",
        {
            "required_sections": [" Introduction ", ""],
            "allowed_page_sizes": ["banana", "a4"],
            "min_image_dpi": 9999,
        },
    )

    assert saved["profile"]["required_sections"] == ["Introduction"]
    assert saved["profile"]["allowed_page_sizes"] == ["A4"]
    assert saved["profile"]["min_image_dpi"] == 2400


def test_overwrite_existing_profile(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    save_latex_profile(workspace, "journal", _PROFILE)

    updated = save_latex_profile(
        workspace, "journal", {**_PROFILE, "required_max_pages": 12}
    )

    assert updated["profile"]["required_max_pages"] == 12
    assert (
        load_latex_profile(workspace, "journal")["profile"]["required_max_pages"] == 12
    )


def test_list_reports_invalid_json(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    directory = workspace / ".sage" / "latex-profiles"
    directory.mkdir(parents=True)
    (directory / "broken.json").write_text("{not json", encoding="utf-8")

    listed = list_latex_profiles(workspace)

    assert listed["profiles"] == []
    assert any(item["code"] == "profile_read_error" for item in listed["warnings"])


def test_delete_missing_profile_raises(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    with pytest.raises(OfficeFileNotFoundError):
        delete_latex_profile(workspace, "missing")


def test_profile_file_has_version_and_evidence(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    save_latex_profile(
        workspace,
        "journal",
        _PROFILE,
        source="guide.md",
        evidence=[{"field": "allowed_page_sizes", "value": "A4"}],
    )

    data = json.loads(
        (workspace / ".sage" / "latex-profiles" / "journal.json").read_text(
            encoding="utf-8"
        )
    )
    assert data["version"] == 1
    assert data["evidence"][0]["field"] == "allowed_page_sizes"
