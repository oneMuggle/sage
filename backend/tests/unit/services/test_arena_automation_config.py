"""Loader tests for backend/config/arena_automation.py (plan §4 D1).

Rule under test: a missing / broken / mistyped yaml must degrade to defaults
with the feature **off** — never fail open, never raise into startup.
"""

import pytest

from backend.config.arena_automation import (
    DEFAULT_CONFIG_PATH,
    ArenaAutomationConfig,
    load_arena_config,
)


def test_missing_file_degrades_to_disabled_defaults(tmp_path):
    cfg = load_arena_config(tmp_path / "nope.yaml")
    assert cfg.enabled is False
    assert cfg.mail_provider == "tenminmail"
    assert cfg.max_accounts == 5
    assert cfg.registration.enabled is False
    assert cfg.registration.concurrency == 3
    assert cfg.draw.enabled is False
    assert cfg.draw.miss_action == "archive"  # user decision Q3
    assert cfg.draw.switch_level is None
    assert cfg.proxy.enabled is False
    assert cfg.proxy.rotation == "per_account"
    assert cfg.token_window.enabled is False
    assert cfg.token_window.max_age_sec == pytest.approx(110.0)


def test_invalid_yaml_degrades(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("enabled: [unclosed\n", encoding="utf-8")
    assert load_arena_config(path).enabled is False


def test_non_mapping_root_degrades(tmp_path):
    path = tmp_path / "list.yaml"
    path.write_text("- 1\n- 2\n", encoding="utf-8")
    assert load_arena_config(path).enabled is False


def test_empty_file_degrades(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    cfg = load_arena_config(path)
    assert cfg.enabled is False
    assert isinstance(cfg, ArenaAutomationConfig)


def test_unknown_key_degrades_instead_of_failing_open(tmp_path):
    path = tmp_path / "typo.yaml"
    path.write_text("enabled: true\nenabeld: true\n", encoding="utf-8")
    assert load_arena_config(path).enabled is False


def test_unknown_sub_key_degrades(tmp_path):
    path = tmp_path / "sub.yaml"
    path.write_text("enabled: true\ndraw:\n  enabled: true\n  keep_patern: x\n", encoding="utf-8")
    cfg = load_arena_config(path)
    assert cfg.enabled is False
    assert cfg.draw.enabled is False


def test_out_of_range_value_degrades(tmp_path):
    path = tmp_path / "range.yaml"
    path.write_text("enabled: true\nmax_accounts: 999\n", encoding="utf-8")
    assert load_arena_config(path).enabled is False


def test_valid_yaml_parses_all_subsections(tmp_path):
    path = tmp_path / "ok.yaml"
    path.write_text(
        "enabled: true\n"
        "max_accounts: 7\n"
        "registration:\n"
        "  enabled: true\n"
        "  concurrency: 5\n"
        "  domains: [a.example]\n"
        "draw:\n"
        "  enabled: true\n"
        "  keep_pattern: 'gpt-5.*'\n"
        "  require_reasoning: true\n"
        "  miss_action: delete\n"
        "  switch_level: 2\n"
        "proxy:\n"
        "  enabled: true\n"
        "  api_url: 'https://proxy.example/api'\n"
        "  api_token: 'sekret'\n"
        "  rotation: per_wave\n"
        "token_window:\n"
        "  enabled: true\n"
        "  use_proxy: true\n",
        encoding="utf-8",
    )
    cfg = load_arena_config(path)
    assert cfg.enabled is True
    assert cfg.max_accounts == 7
    assert cfg.registration.concurrency == 5
    assert cfg.registration.domains == ["a.example"]
    assert cfg.draw.keep_pattern == "gpt-5.*"
    assert cfg.draw.require_reasoning is True
    assert cfg.draw.miss_action == "delete"
    assert cfg.draw.switch_level == 2
    assert cfg.proxy.api_token == "sekret"
    assert cfg.proxy.rotation == "per_wave"
    assert cfg.token_window.enabled is True
    assert cfg.token_window.use_proxy is True


def test_shipped_yaml_is_valid_and_disabled():
    """Guards the committed default file: it must parse and stay off."""
    cfg = load_arena_config(DEFAULT_CONFIG_PATH)
    assert cfg.enabled is False
    assert cfg.registration.enabled is False
    assert cfg.draw.enabled is False
    assert cfg.proxy.enabled is False
    assert cfg.token_window.enabled is False
    assert cfg.mail_provider in ("tenminmail", "mailtm")
    assert cfg.draw.miss_action in ("archive", "delete", "keep")
