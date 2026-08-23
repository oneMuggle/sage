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


def test_worktree_isolation_bool_override_and_bad_value_falls_back():
    """worktreeIsolation 只接受 bool，默认关闭。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"worktreeIsolation": True}
        }
        s = load_orch_settings()
    assert s.worktree_isolation is True

    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"worktreeIsolation": 1}
        }
        s = load_orch_settings()
    assert s.worktree_isolation is False


# --------------------------------------------------------------------------- #
# max_subagent_iterations —— 子代理迭代预算配置化
#
# 此前 backend/tools/agent_tool.py 用模块级常量 SUBAGENT_MAX_ITERATIONS = 6
# 硬编码，用户撞上限后无法自助调整。纳入 orch 段后与 maxLaneIterations 对等。
# --------------------------------------------------------------------------- #


def test_max_subagent_iterations_default_is_6():
    """无 app_settings → 回落 6，与原硬编码常量保持一致（不改变既有行为）。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = None
        s = load_orch_settings()
    assert s.max_subagent_iterations == 6


def test_max_subagent_iterations_override():
    """app_settings.orch.maxSubagentIterations 覆盖生效。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxSubagentIterations": 12}
        }
        s = load_orch_settings()
    assert s.max_subagent_iterations == 12
    # 同段其他键不受影响
    assert s.max_lane_iterations == 8


def test_max_subagent_iterations_bad_value_falls_back():
    """坏类型（str / bool）只回落该键，不污染整段。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxSubagentIterations": "12", "maxRetries": 5}
        }
        s = load_orch_settings()
    assert s.max_subagent_iterations == 6
    assert s.max_retries == 5

    # bool 是 int 子类 —— 必须显式排除，否则 True 会被当成 1
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxSubagentIterations": True}
        }
        s = load_orch_settings()
    assert s.max_subagent_iterations == 6
