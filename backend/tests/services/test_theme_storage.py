"""Tests for ThemeStorage atomic JSON persistence (py3.10+, pydantic 2.x)."""
import json
from pathlib import Path

import pytest

from backend.schemas.theme import ActiveTheme, ThemePreset
from backend.services.theme_storage import ThemeStorage


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """Provide a clean data directory with defaults.json pre-seeded."""
    d = tmp_path / "data"
    d.mkdir()
    defaults = [
        {
            "id": "light",
            "name": "theme.presets.light.name",
            "description": "theme.presets.light.description",
            "cover": "/assets/light.png",
        },
        {
            "id": "dark",
            "name": "theme.presets.dark.name",
            "description": "theme.presets.dark.description",
            "cover": "/assets/dark.png",
        },
    ]
    (d / "themes.defaults.json").write_text(json.dumps(defaults), encoding="utf-8")
    return d


# --- seed & list ---

def test_seeds_themes_json_on_first_access(data_dir: Path):
    """First list() creates themes.json from defaults."""
    storage = ThemeStorage(data_dir)
    presets = storage.list()
    assert len(presets) == 2
    assert {p.id for p in presets} == {"light", "dark"}
    assert (data_dir / "themes.json").exists()


def test_list_does_not_overwrite_existing_themes_json(data_dir: Path):
    """If themes.json exists, list() does not re-seed."""
    existing = [{"id": "user-1", "name": "n", "description": "d"}]
    (data_dir / "themes.json").write_text(json.dumps(existing), encoding="utf-8")
    storage = ThemeStorage(data_dir)
    presets = storage.list()
    assert len(presets) == 1
    assert presets[0].id == "user-1"


# --- get ---

def test_get_existing_preset_returns_model(data_dir: Path):
    storage = ThemeStorage(data_dir)
    preset = storage.get("light")
    assert preset is not None
    assert preset.id == "light"
    assert isinstance(preset, ThemePreset)


def test_get_missing_preset_returns_none(data_dir: Path):
    storage = ThemeStorage(data_dir)
    assert storage.get("nope") is None


# --- save ---

def test_save_preserves_existing_and_adds_new(data_dir: Path):
    storage = ThemeStorage(data_dir)
    storage.list()  # seed
    new = ThemePreset(id="ocean", name="n", description="d", cover="/o.png")
    storage.save(new)
    all_presets = storage.list()
    assert {p.id for p in all_presets} == {"light", "dark", "ocean"}


def test_save_overwrites_existing_id(data_dir: Path):
    storage = ThemeStorage(data_dir)
    storage.list()
    updated = ThemePreset(id="light", name="NEW", description="NEW", cover="/l.png")
    storage.save(updated)
    got = storage.get("light")
    assert got.name == "NEW"


# --- delete ---

def test_delete_existing_returns_true(data_dir: Path):
    storage = ThemeStorage(data_dir)
    storage.list()
    assert storage.delete("light") is True
    assert storage.get("light") is None


def test_delete_missing_returns_false(data_dir: Path):
    storage = ThemeStorage(data_dir)
    storage.list()
    assert storage.delete("nope") is False


# --- active ---

def test_get_active_default_is_light(data_dir: Path):
    storage = ThemeStorage(data_dir)
    storage.list()
    active = storage.get_active()
    assert active.presetId == "light"
    assert active.customCss is None


def test_save_active_then_get_roundtrips(data_dir: Path):
    storage = ThemeStorage(data_dir)
    storage.list()
    storage.save_active(ActiveTheme(presetId="ocean", customCss=":root {}"))
    loaded = storage.get_active()
    assert loaded.presetId == "ocean"
    assert loaded.customCss == ":root {}"


# --- atomic write & corruption ---

def test_atomic_write_no_partial_file_on_disk_failure(data_dir: Path, monkeypatch):
    """If write fails mid-way, themes.json is not corrupted."""
    storage = ThemeStorage(data_dir)
    storage.list()

    # Force os.fdopen to fail (used inside _atomic_write_json after mkstemp
    # creates the temp file but BEFORE os.replace). This simulates a disk-full
    # mid-write. themes.json must remain valid (the previous successful write
    # is still on disk; the failed temp file must be cleaned up).
    import os as _os

    def fail_fdopen(fd, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(_os, "fdopen", fail_fdopen)
    with pytest.raises(OSError):
        storage.save(ThemePreset(id="x", name="n", description="d"))
    # themes.json should still be parseable (the previous seed is intact)
    content = json.loads((data_dir / "themes.json").read_text(encoding="utf-8"))
    assert isinstance(content, list)  # valid JSON, not corrupted
    # The orphan .tmp_ file must not be left behind
    tmp_leftovers = list(data_dir.glob(".tmp_*.json"))
    assert tmp_leftovers == [], f"orphan temp files left: {tmp_leftovers}"


def test_corrupted_themes_json_falls_back_to_defaults(data_dir: Path):
    """If themes.json is corrupted, re-seed from defaults (backup corrupted file)."""
    (data_dir / "themes.json").write_text("{ this is not json", encoding="utf-8")
    storage = ThemeStorage(data_dir)
    presets = storage.list()
    assert len(presets) == 2  # re-seeded
    # backup file should exist
    backups = list(data_dir.glob("themes.json.bak.*"))
    assert len(backups) == 1
