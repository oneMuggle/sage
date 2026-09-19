"""arena_automation.yaml 加载器测试（fail-safe 语义）。"""

from __future__ import annotations

from pathlib import Path

from backend.config.arena_automation import load_arena_automation_config


def test_missing_file_returns_defaults(tmp_path: Path):
    cfg = load_arena_automation_config(tmp_path / "nope.yaml")
    assert cfg.enabled is False
    assert cfg.max_accounts == 5
    assert cfg.probe_backend == "python"


def test_valid_file_round_trip(tmp_path: Path):
    path = tmp_path / "arena_automation.yaml"
    path.write_text(
        "enabled: true\nmax_accounts: 8\nmail_provider: mailtm\n",
        encoding="utf-8",
    )
    cfg = load_arena_automation_config(path)
    assert cfg.enabled is True
    assert cfg.max_accounts == 8


def test_malformed_yaml_falls_back_to_defaults(tmp_path: Path):
    path = tmp_path / "arena_automation.yaml"
    path.write_text("enabled: [unclosed\n  bad", encoding="utf-8")
    cfg = load_arena_automation_config(path)
    assert cfg.enabled is False


def test_unknown_field_falls_back_to_defaults(tmp_path: Path):
    path = tmp_path / "arena_automation.yaml"
    path.write_text("enabled: true\nno_such_field: 1\n", encoding="utf-8")
    cfg = load_arena_automation_config(path)
    assert cfg.enabled is False  # ValidationError → 默认（关）


def test_repo_yaml_file_exists_and_disabled():
    from backend.config.arena_automation import DEFAULT_CONFIG_PATH

    assert DEFAULT_CONFIG_PATH.is_file()
    cfg = load_arena_automation_config()
    assert cfg.enabled is False  # 仓库默认必须关
