"""M3.3: Planner 预估字段（estimated_iterations / complexity）+ 深层拆分开关。"""

from __future__ import annotations

from unittest.mock import patch

from backend.orchestration.orch_settings import OrchSettings
from backend.orchestration.planner import (
    MAX_ESTIMATED_ITERATIONS,
    Planner,
    sanitize_llm_plan_tasks,
)
from backend.orchestration.task_registry import TaskRegistry
from backend.orchestration.team_registry import TeamRegistry


def _planner() -> Planner:
    return Planner(TaskRegistry(), TeamRegistry(), auto_configure=False)


def test_sanitize_keeps_estimated_fields():
    tasks = sanitize_llm_plan_tasks(
        [
            {
                "id": "t1",
                "title": "A",
                "description": "d",
                "estimated_iterations": 4,
                "complexity": "High",
            }
        ]
    )
    assert tasks[0]["parameters"]["estimated_iterations"] == 4
    assert tasks[0]["parameters"]["complexity"] == "high"


def test_sanitize_drops_invalid_estimates():
    tasks = sanitize_llm_plan_tasks(
        [
            {"title": "A", "description": "d", "estimated_iterations": 0, "complexity": "extreme"},
            {"title": "B", "description": "d", "estimated_iterations": "6", "complexity": 3},
            {"title": "C", "description": "d", "estimated_iterations": True},
            {"title": "D", "description": "d", "estimated_iterations": 51},
        ]
    )
    for task in tasks:
        assert "estimated_iterations" not in task["parameters"]
        assert "complexity" not in task["parameters"]


def test_sanitize_respects_max_estimated_iterations():
    """prompt 契约上限 = sanitizer 上限（常量单一来源，避免契约漂移）。"""
    tasks = sanitize_llm_plan_tasks(
        [
            {
                "title": "at-limit",
                "description": "d",
                "estimated_iterations": MAX_ESTIMATED_ITERATIONS,
            },
            {
                "title": "over-limit",
                "description": "d",
                "estimated_iterations": MAX_ESTIMATED_ITERATIONS + 1,
            },
        ]
    )
    assert tasks[0]["parameters"]["estimated_iterations"] == MAX_ESTIMATED_ITERATIONS
    assert "estimated_iterations" not in tasks[1]["parameters"]


def test_prompt_includes_estimate_fields():
    prompt = _planner()._build_decomposition_prompt("目标")
    assert "estimated_iterations" in prompt
    assert "complexity" in prompt
    assert "integer 1-15" in prompt


def test_prompt_forbids_parent_when_deep_disabled():
    with patch(
        "backend.orchestration.orch_settings.load_orch_settings"
    ) as load:
        load.return_value = OrchSettings(allow_deep_decomposition=False)
        prompt = _planner()._build_decomposition_prompt("目标")
    assert 'Do NOT use "parent_task_id"' in prompt
    assert "subtasks allowed" not in prompt


def test_prompt_allows_parent_when_deep_enabled():
    with patch(
        "backend.orchestration.orch_settings.load_orch_settings"
    ) as load:
        load.return_value = OrchSettings(allow_deep_decomposition=True)
        prompt = _planner()._build_decomposition_prompt("目标")
    assert "subtasks allowed" in prompt
    assert 'Do NOT use "parent_task_id"' not in prompt


def test_load_settings_allow_deep_decomposition():
    with patch(
        "backend.orchestration.orch_settings.SettingsRepository"
    ) as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"allowDeepDecomposition": True}
        }
        from backend.orchestration.orch_settings import load_orch_settings

        settings = load_orch_settings()
    assert settings.allow_deep_decomposition is True


# --------------------------------------------------------------------------- #
# 设置键落库链路（relay snake 往返 + 编排段白名单）
#
# 历史上新加的编排开关漏登记 canonicalizer 时，编排段任一次保存都被
# validate_settings_shape 判 400，且前端 saveSettings 的 catch 静默吞错
# —— 用户看到"改了没生效"。这里把漏登记变成机械可检。
# --------------------------------------------------------------------------- #


def test_new_setting_key_survives_relay_snake_roundtrip():
    """前端 camelCase → electron camelToSnake → 后端 to_camel 必须翻回 camel。"""
    from backend.data.settings_canonicalizer import from_camel, to_camel

    payload = {"orch": {"allow_deep_decomposition": True}}
    assert to_camel(payload) == {"orch": {"allowDeepDecomposition": True}}
    assert from_camel({"orch": {"allowDeepDecomposition": True}}) == payload


def test_orch_section_with_new_key_passes_shape_validation():
    """翻译后的编排段必须能通过白名单校验（否则保存 400）。"""
    from backend.data.settings_canonicalizer import to_camel, validate_settings_shape

    validate_settings_shape(to_camel({"orch": {"allow_deep_decomposition": True}}))
