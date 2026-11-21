"""Unit tests for the file-backed design tweaks store."""
from __future__ import annotations

from backend.design.tweaks_store import ProjectTweaks, TweaksStore


def test_get_unknown_project_returns_none(tmp_path):
    assert TweaksStore(tmp_path).get("missing") is None


def test_put_and_get_round_trip(tmp_path):
    store = TweaksStore(tmp_path)
    tweaks = ProjectTweaks(
        accent="#1a56db", radius=6, font_size=16, density=16,
        font_family="Georgia, serif",
    )
    store.put("p1", tweaks)
    loaded = store.get("p1")
    assert loaded is not None
    assert loaded.accent == "#1a56db"
    assert loaded.radius == 6
    assert loaded.font_size == 16
    assert loaded.density == 16
    assert loaded.font_family == "Georgia, serif"


def test_update_merges_partial_fields(tmp_path):
    store = TweaksStore(tmp_path)
    store.put("p1", ProjectTweaks(accent="#000000", radius=0))
    updated = store.update("p1", radius=8, density=20, font_family="Menlo, monospace")
    assert updated.accent == "#000000"
    assert updated.radius == 8
    assert updated.density == 20
    assert updated.font_family == "Menlo, monospace"
    assert updated.font_size is None


def test_update_on_missing_project_creates_file(tmp_path):
    store = TweaksStore(tmp_path)
    updated = store.update("p1", accent="#cc0000")
    assert updated.accent == "#cc0000"
    assert store.get("p1") is not None


def test_clear_resets_overrides(tmp_path):
    store = TweaksStore(tmp_path)
    store.put("p1", ProjectTweaks(accent="#111111", font_family="Georgia, serif"))
    cleared = store.clear("p1")
    assert cleared.accent is None
    assert cleared.font_family is None
    assert store.get("p1").accent is None


def test_get_corrupt_file_returns_none(tmp_path):
    project_dir = tmp_path / "p1"
    project_dir.mkdir()
    (project_dir / "tweaks.json").write_text("{not json", encoding="utf-8")
    assert TweaksStore(tmp_path).get("p1") is None


def test_projects_are_isolated(tmp_path):
    store = TweaksStore(tmp_path)
    store.put("p1", ProjectTweaks(accent="#111111"))
    store.put("p2", ProjectTweaks(accent="#222222"))
    assert store.get("p1").accent == "#111111"
    assert store.get("p2").accent == "#222222"
