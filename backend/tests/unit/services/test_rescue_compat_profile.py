"""Rescue compat profile — 兼容档位持久化."""
from __future__ import annotations

import json

from backend.services.rescue import compat_profile as cp


def test_new_profile_defaults_to_l0():
    p = cp.new_profile()
    assert p["schema"] == cp.CURRENT_SCHEMA
    assert p["level"] == 0
    assert p["flags"] == []
    assert p["app"]["petWindow"] is True
    assert p["app"]["browserBridge"] is True


def test_new_profile_l1_disables_pet_and_preview():
    p = cp.new_profile(level=1, reason="renderer crashed")
    assert p["level"] == 1
    assert p["app"]["petWindow"] is False
    assert p["app"]["previewHost"] is False
    assert p["app"]["browserBridge"] is True
    assert "disable-gpu-compositing" in p["flags"]


def test_new_profile_rejects_out_of_range():
    import pytest

    with pytest.raises(ValueError, match="level"):
        cp.new_profile(level=4)


def test_bump_level_caps_at_max():
    p = cp.new_profile(level=2)
    bumped = cp.bump_level(p, reason="crash")
    assert bumped["level"] == 3
    bumped_again = cp.bump_level(bumped, reason="crash")
    assert bumped_again["level"] == 3  # 不再升


def test_reset_level_returns_l0():
    cp.new_profile(level=3, reason="experiment")
    reset = cp.reset_level(reason="user")
    assert reset["level"] == 0
    assert reset["reason"] == "user"


def test_read_missing_returns_default(tmp_path):
    p = cp.read_profile(tmp_path)
    assert p["level"] == 0
    assert p["schema"] == cp.CURRENT_SCHEMA


def test_read_invalid_schema_returns_default(tmp_path):
    diag = tmp_path / "diagnostics"
    diag.mkdir()
    (diag / "compat.json").write_text('{"schema": 999, "level": 2}', encoding="utf-8")
    p = cp.read_profile(tmp_path)
    assert p["level"] == 0


def test_read_valid_persists(tmp_path):
    diag = tmp_path / "diagnostics"
    diag.mkdir()
    data = cp.new_profile(level=2, reason="test")
    (diag / "compat.json").write_text(json.dumps(data), encoding="utf-8")
    p = cp.read_profile(tmp_path)
    assert p["level"] == 2
    assert p["reason"] == "test"


def test_set_level_writes_and_reads(tmp_path):
    p = cp.set_level(1, reason="manual", user_data_dir=tmp_path)
    assert p["level"] == 1
    assert (tmp_path / "diagnostics" / "compat.json").is_file()
    reloaded = cp.read_profile(tmp_path)
    assert reloaded["level"] == 1


def test_effective_flags_and_features_match_level():
    p = cp.new_profile(level=2)
    assert cp.effective_flags(p) == [
        "disable-gpu-compositing",
        "disable-accelerated-2d-canvas",
        "disable-site-isolation-trials",
    ]
    features = cp.effective_app_features(p)
    assert features["browserBridge"] is False
    assert features["petWindow"] is False
