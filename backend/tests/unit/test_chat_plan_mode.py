"""PM1 (round8) — 单 agent 计划模式字段与指令单测。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_chat_request_plan_mode_defaults_false():
    from backend.api.legacy_routes import ChatRequest

    req = ChatRequest(session_id="s", message="hi")
    assert req.plan_mode is False
    req2 = ChatRequest(session_id="s", message="hi", plan_mode=True)
    assert req2.plan_mode is True


def test_plan_mode_directive_content():
    from backend.api.legacy_routes import _PLAN_MODE_DIRECTIVE

    assert "计划模式" in _PLAN_MODE_DIRECTIVE
    assert "只读" in _PLAN_MODE_DIRECTIVE
    assert "## 分步计划" in _PLAN_MODE_DIRECTIVE
