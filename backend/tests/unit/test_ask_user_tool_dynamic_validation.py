"""2026-10-28 — ask_user_question 选项数的动态验证。

工具的 JSON schema 保持静态 2-4（LLM 视角的契约稳定），
但运行期校验改由 OrchSettings 驱动 —— 用户可在设置页放宽或收紧。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.tools.ask_user_tool import validate_ask_user_args

pytestmark = pytest.mark.unit


def _args(n: int) -> dict:
    return {
        "question": "选择输出格式?",
        "header": "输出格式",
        "options": [{"label": f"选项{i}"} for i in range(n)],
        "multi_select": False,
    }


def test_validate_options_uses_dynamic_min_max():
    """动态限制生效：min=3 时 2 个选项被拒；max=6 时 5 个选项通过。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {"minOptionsPerQuestion": 3, "maxOptionsPerQuestion": 6}
        }
        err = validate_ask_user_args(_args(2))
        assert err is not None
        assert "3-6" in err

        err = validate_ask_user_args(_args(5))
        assert err is None


def test_validate_options_default_limits_unchanged():
    """无配置 → 保持 2-4 的既有约束。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = None
        assert validate_ask_user_args(_args(2)) is None
        assert validate_ask_user_args(_args(4)) is None
        err = validate_ask_user_args(_args(5))
        assert err is not None
        assert "2-4" in err


def test_validate_options_falls_back_when_settings_broken():
    """配置读取抛错 → 回落硬编码默认，不抛穿。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.side_effect = RuntimeError("db down")
        assert validate_ask_user_args(_args(2)) is None
        err = validate_ask_user_args(_args(5))
        assert err is not None
        assert "2-4" in err


def test_tool_schema_reflects_current_settings():
    """JSON schema 反映当前设置 —— 与运行期校验保持一致。

    2026-10-28 review (HIGH-2): 之前 schema 静态 2-4，运行期按配置动态校验 →
    用户把 min 调到 3 时 LLM 按 schema 出 2 选项会被运行期拒掉。现已改为
    动态 schema。默认设置下仍是 2-4；改配置后 schema 同步变化。
    """
    from backend.tools.ask_user_tool import AskUserQuestionTool

    # 默认设置 → 2-4
    options_schema = AskUserQuestionTool().schema.parameters["properties"]["options"]
    assert options_schema["minItems"] == 2
    assert options_schema["maxItems"] == 4


def test_tool_schema_dynamic_when_settings_change(monkeypatch):
    """用户把 min/max 调到 3-6 时，schema 同步变化 —— 与运行期校验一致。"""
    from backend.tools import ask_user_tool

    monkeypatch.setattr(
        ask_user_tool,
        "_load_ask_user_limits",
        lambda: {"min_options_per_question": 3, "max_options_per_question": 6},
    )
    from backend.tools.ask_user_tool import AskUserQuestionTool

    options_schema = AskUserQuestionTool().schema.parameters["properties"]["options"]
    assert options_schema["minItems"] == 3
    assert options_schema["maxItems"] == 6
    # description 也反映当前区间（LLM 指引与实际约束一致）
    assert "3-6" in options_schema["description"]
