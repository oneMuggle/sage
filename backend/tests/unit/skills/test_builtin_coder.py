"""R134 — 内置编程技能（CoderSkill）单元测试。

覆盖：schema 契约（name/required/action 枚举）、五动作 prompt 构建
（write 用 requirement、其余 code 围栏）、language 缺省、未知操作、
无 LLM 模拟回退（metadata.mock）、LLM 分派与异常映射。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.skills.builtin.coder import CoderSkill

pytestmark = pytest.mark.unit


def test_schema_contract():
    schema = CoderSkill().schema
    assert schema.name == "coder"
    assert schema.parameters["required"] == ["action"]
    assert set(schema.parameters["properties"]["action"]["enum"]) == {
        "write",
        "explain",
        "debug",
        "review",
        "refactor",
    }


def _llm(capture):
    def complete(prompt):
        capture.append(prompt)
        return f"llm-response: {prompt[:12]}"

    return SimpleNamespace(complete=complete)


@pytest.mark.parametrize(
    ("action", "fragment"),
    [
        ("write", "代码示例"),
        ("explain", "主要功能是"),
        ("debug", "代码检查结果"),
        ("review", "代码审查建议"),
        ("refactor", "重构后的"),
    ],
)
def test_five_actions_build_prompts(action, fragment):
    out = CoderSkill().execute(
        {"action": action, "language": "python", "code": "x=1", "requirement": "排序"},
        {},
    )
    assert out.success is True
    assert out.metadata["action"] == action
    assert out.metadata["mock"] is True  # 无 LLM → 模拟回退
    assert fragment in out.content


def test_language_defaults_to_python():
    out = CoderSkill().execute({"action": "explain", "code": "a=1"}, {})
    assert out.metadata["language"] == "python"


def test_unknown_action_rejected():
    out = CoderSkill().execute({"action": "hack"}, {})
    assert out.success is False
    assert "未知操作" in out.error


def test_llm_dispatch_returns_completion():
    prompts = []
    llm = _llm(prompts)
    out = CoderSkill().execute(
        {"action": "write", "requirement": "快速排序", "language": "python"},
        {"llm": llm},
    )
    assert out.success is True
    assert out.content.startswith("llm-response:")
    assert len(prompts) == 1
    assert "快速排序" in prompts[0]
    assert "mock" not in out.metadata  # 真实 LLM 路径无 mock 标记


def test_llm_exception_maps_to_error():
    def complete(_prompt):
        raise RuntimeError("quota exceeded")

    out = CoderSkill().execute(
        {"action": "write", "requirement": "r"}, {"llm": SimpleNamespace(complete=complete)}
    )
    assert out.success is False
    assert "代码生成失败" in out.error
    assert "quota exceeded" in out.error
