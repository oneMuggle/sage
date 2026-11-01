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
    assert s.max_lane_iterations == 12  # alpha.36 (Bug #2): 8 → 12


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


def test_max_subagent_iterations_default_is_10():
    """无 app_settings → 回落 10 (alpha.36: 6 → 10, 减少"复杂度超上限"误报)。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = None
        s = load_orch_settings()
    assert s.max_subagent_iterations == 10


def test_max_subagent_iterations_override():
    """app_settings.orch.maxSubagentIterations 覆盖生效。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxSubagentIterations": 12}
        }
        s = load_orch_settings()
    assert s.max_subagent_iterations == 12
    # 同段其他键不受影响
    assert s.max_lane_iterations == 12  # alpha.36 (Bug #2): 8 → 12


def test_max_subagent_iterations_bad_value_falls_back():
    """坏类型（str / bool）只回落该键，不污染整段。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxSubagentIterations": "12", "maxRetries": 5}
        }
        s = load_orch_settings()
    assert s.max_subagent_iterations == 10  # alpha.36 (Bug #2): 6 → 10
    assert s.max_retries == 5

    # bool 是 int 子类 —— 必须显式排除，否则 True 会被当成 1
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxSubagentIterations": True}
        }
        s = load_orch_settings()
    assert s.max_subagent_iterations == 10  # alpha.36 (Bug #2): 6 → 10


# ---------------------------------------------------------------------------
# 2026-10-27 — 计划前置 / Planner 迭代预算旋钮
# ---------------------------------------------------------------------------


def test_iteration_budgets_default_values():
    """无 app_settings → Scout 4 / Planner 8（既有硬编码行为 + 总方案建议值）。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = None
        s = load_orch_settings()
    assert s.max_scout_iterations == 4
    assert s.max_planner_iterations == 8


def test_iteration_budgets_override():
    """app_settings.orch 的 camelCase 键覆盖生效，且互不影响。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxScoutIterations": 2, "maxPlannerIterations": 12}
        }
        s = load_orch_settings()
    assert s.max_scout_iterations == 2
    assert s.max_planner_iterations == 12
    # 同段其他键不受影响
    assert s.max_subagent_iterations == 10


def test_iteration_budgets_bad_value_falls_back():
    """坏类型（str / bool）只回落该键，不污染整段。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {
                "maxScoutIterations": "2",
                "maxPlannerIterations": True,
                "maxRetries": 5,
            }
        }
        s = load_orch_settings()
    assert s.max_scout_iterations == 4
    assert s.max_planner_iterations == 8
    assert s.max_retries == 5


def test_iteration_budgets_clamped_to_lower_bound():
    """0 / 负值被钳到 1 —— 0 会让 ReAct 循环零次执行直接判定超限。

    前端 NumberField 有 ``min={1}`` 守卫，但 API 可绕过 UI 直写脏数据；
    后端在此兜底，避免侦察静默失效（无异常、无日志、比崩溃更难排查）。
    """
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxScoutIterations": 0, "maxPlannerIterations": -3}
        }
        s = load_orch_settings()
    assert s.max_scout_iterations == 1
    assert s.max_planner_iterations == 1


# ---------------------------------------------------------------------------
# 2026-11-01 — 动态迭代预算（P1 设置页暴露）
# ---------------------------------------------------------------------------


def test_dynamic_budget_overrides_and_clamps():
    """7 个新键走 camelCase 映射；预算/硬顶下界 1，延长次数允许 0。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {
                "dynamicBudgetEnabled": False,
                "budgetSimple": 12,
                "budgetMedium": 90,
                "budgetComplex": 300,
                "budgetLong": 600,
                "budgetHardCap": 2000,
                "budgetMaxExtensions": 5,
            }
        }
        s = load_orch_settings()
    assert s.dynamic_budget_enabled is False
    assert s.budget_simple == 12
    assert s.budget_medium == 90
    assert s.budget_complex == 300
    assert s.budget_long == 600
    assert s.budget_hard_cap == 2000
    assert s.budget_max_extensions == 5


def test_dynamic_budget_defaults_and_lower_bounds():
    """缺省值 20/80/200/400/1000/3；预算与硬顶低于 1 时钳到 1，
    延长次数允许 0（表示不自动延长）。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = None
        s = load_orch_settings()
    assert s.dynamic_budget_enabled is True
    assert (s.budget_simple, s.budget_medium, s.budget_complex, s.budget_long) == (
        20,
        80,
        200,
        400,
    )
    assert s.budget_hard_cap == 1000
    assert s.budget_max_extensions == 3

    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {
                "budgetSimple": 0,
                "budgetMedium": -1,
                "budgetHardCap": 0,
                "budgetMaxExtensions": -2,
            }
        }
        s = load_orch_settings()
    assert s.budget_simple == 1
    assert s.budget_medium == 1
    assert s.budget_hard_cap == 1
    assert s.budget_max_extensions == 0
