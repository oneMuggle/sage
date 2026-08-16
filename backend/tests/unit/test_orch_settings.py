"""P2-9 — orch_settings 配置化：默认值 + app_settings 覆盖 + 缺 orch 段回落。"""
from __future__ import annotations

from unittest.mock import patch

from backend.orchestration.orch_settings import OrchSettings, load_orch_settings


def test_defaults_when_no_app_settings():
    """SettingsRepository 无数据 / 抛错 → 全默认。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = None
        s = load_orch_settings()
    assert s == OrchSettings()
    assert s.max_concurrent_subagents == 4
    assert s.max_aggregate_chars == 120 * 1024
    assert s.scratch_root == "orch_scratch"


def test_overrides_from_app_settings_orch_section():
    """app_settings.orch 段覆盖对应键（camelCase 键名）。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {
                "maxConcurrentSubagents": 8,
                "maxRetries": 3,
                "scratchRoot": "custom_scratch",
            }
        }
        s = load_orch_settings()
    assert s.max_concurrent_subagents == 8
    assert s.max_retries == 3
    assert s.scratch_root == "custom_scratch"
    # 未覆盖键回落默认
    assert s.max_aggregate_chars == 120 * 1024
    assert s.max_lane_iterations == 8


def test_bad_typed_keys_fall_back_per_key():
    """单个坏键（非目标类型）只回落该键默认，不整段丢弃。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {
                "maxConcurrentSubagents": "8",  # str 而非 int → 回落
                "maxSubagentResultChars": 30_000,  # 合法
            }
        }
        s = load_orch_settings()
    assert s.max_concurrent_subagents == 4
    assert s.max_subagent_result_chars == 30_000
