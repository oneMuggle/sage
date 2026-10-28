"""2026-10-28 — ask_user_question 限制配置化的 OrchSettings 装载与消费方行为。

覆盖 5 个新 orch 键的默认值 / 覆盖 / 坏值回落 / 下界钳制，
以及四个消费方（agent 连续未应答上限 / profiles 澄清指引 /
plan_preflight 单轮上限）的动态读取与 fail-safe 回落。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# OrchSettings 装载
# --------------------------------------------------------------------------- #


def test_ask_user_limits_default_values():
    """无 app_settings → 回落既有硬编码行为。"""
    from backend.orchestration.orch_settings import load_orch_settings

    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = None
        s = load_orch_settings()

    assert s.max_consecutive_unanswered_questions == 3
    assert s.min_options_per_question == 2
    assert s.max_options_per_question == 4
    assert s.max_clarify_questions_in_prompt == 2
    assert s.max_clarify_questions_per_round == 3


def test_ask_user_limits_override():
    """app_settings.orch 的 camelCase 键覆盖生效，且不影响同段其他键。"""
    from backend.orchestration.orch_settings import load_orch_settings

    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {
                "maxConsecutiveUnansweredQuestions": 1,
                "minOptionsPerQuestion": 3,
                "maxOptionsPerQuestion": 6,
                "maxClarifyQuestionsInPrompt": 4,
                "maxClarifyQuestionsPerRound": 5,
            }
        }
        s = load_orch_settings()

    assert s.max_consecutive_unanswered_questions == 1
    assert s.min_options_per_question == 3
    assert s.max_options_per_question == 6
    assert s.max_clarify_questions_in_prompt == 4
    assert s.max_clarify_questions_per_round == 5
    # 同段其他键不受影响
    assert s.max_scout_iterations == 4


def test_ask_user_limits_bad_type_falls_back_per_key():
    """坏类型（str / bool）只回落该键，不污染整段。"""
    from backend.orchestration.orch_settings import load_orch_settings

    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {
                "maxConsecutiveUnansweredQuestions": "1",
                "minOptionsPerQuestion": True,
                "maxOptionsPerQuestion": 6,
                "maxRetries": 5,
            }
        }
        s = load_orch_settings()

    assert s.max_consecutive_unanswered_questions == 3
    assert s.min_options_per_question == 2
    assert s.max_options_per_question == 6
    assert s.max_retries == 5


def test_ask_user_limits_clamped_to_lower_bound():
    """0 / 负值被钳到 1 —— 这些限制的 0 值无意义。"""
    from backend.orchestration.orch_settings import load_orch_settings

    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {
                "maxConsecutiveUnansweredQuestions": 0,
                "minOptionsPerQuestion": -1,
                "maxOptionsPerQuestion": 0,
                "maxClarifyQuestionsInPrompt": -5,
                "maxClarifyQuestionsPerRound": 0,
            }
        }
        s = load_orch_settings()

    assert s.max_consecutive_unanswered_questions == 1
    assert s.min_options_per_question == 1
    assert s.max_options_per_question == 1
    assert s.max_clarify_questions_in_prompt == 1
    assert s.max_clarify_questions_per_round == 1


# --------------------------------------------------------------------------- #
# agent 连续未应答上限
# --------------------------------------------------------------------------- #


def test_load_max_consecutive_unanswered_reads_settings():
    """动态读取连续未应答上限。"""
    from backend.core.legacy.agent import _load_max_consecutive_unanswered

    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxConsecutiveUnansweredQuestions": 7}
        }
        assert _load_max_consecutive_unanswered() == 7


def test_load_max_consecutive_unanswered_falls_back():
    """读取失败 → 回落硬编码常量 3。"""
    from backend.core.legacy.agent import (
        MAX_CONSECUTIVE_UNANSWERED_QUESTIONS,
        _load_max_consecutive_unanswered,
    )

    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.side_effect = RuntimeError("db down")
        assert _load_max_consecutive_unanswered() == MAX_CONSECUTIVE_UNANSWERED_QUESTIONS


# --------------------------------------------------------------------------- #
# profiles 澄清指引
# --------------------------------------------------------------------------- #


def test_clarify_guidance_interpolates_configured_count():
    """提示词中的问题数随配置变化。"""
    from backend.agents import profiles

    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxClarifyQuestionsInPrompt": 5}
        }
        guidance = profiles._build_clarify_guidance()
    assert "至多 5 个问题" in guidance


def test_clarify_guidance_default_count_is_two():
    """无配置 → 保持既有的「至多 2 个问题」。"""
    from backend.agents import profiles

    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = None
        guidance = profiles._build_clarify_guidance()
    assert "至多 2 个问题" in guidance


def test_build_system_base_contains_dynamic_guidance():
    """系统基座包含动态澄清指引（不再硬编码 2）。"""
    from backend.agents import profiles

    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxClarifyQuestionsInPrompt": 3}
        }
        base = profiles.build_system_base()
    assert "至多 3 个问题" in base


# --------------------------------------------------------------------------- #
# plan_preflight 单轮澄清上限
# --------------------------------------------------------------------------- #


def test_load_max_clarify_questions_per_round_reads_settings():
    """动态读取单轮澄清提问数上限。"""
    from backend.orchestration.plan_preflight import (
        _load_max_clarify_questions_per_round,
    )

    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"maxClarifyQuestionsPerRound": 9}
        }
        assert _load_max_clarify_questions_per_round() == 9


def test_load_max_clarify_questions_per_round_falls_back():
    """读取失败 → 回落硬编码常量 3。"""
    from backend.orchestration.plan_preflight import (
        MAX_CLARIFY_QUESTIONS,
        _load_max_clarify_questions_per_round,
    )

    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.side_effect = RuntimeError("db down")
        assert _load_max_clarify_questions_per_round() == MAX_CLARIFY_QUESTIONS
