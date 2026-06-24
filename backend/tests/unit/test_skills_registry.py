"""
SkillRegistry 单元测试

覆盖：
- register / unregister / get / exists
- 重复注册覆盖并打 WARNING 日志
- list / list_names / clear
- match / match_all
- execute 正常路径 + 异常包装成 SkillResult(success=False)
- execute 无匹配返回 None
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

from backend.skills.base import BaseSkill, SkillResult, SkillSchema
from backend.skills.registry import SkillRegistry

pytestmark = pytest.mark.unit


# ============================================================================
# helpers
# ============================================================================


def _make_skill(name: str = "x", triggers: list[str] | None = None) -> BaseSkill:
    class _S(BaseSkill):
        def _build_schema(self) -> SkillSchema:
            return SkillSchema(
                name=name,
                description=f"{name} skill",
                triggers=triggers or [name],
                parameters={"type": "object", "properties": {}, "required": []},
            )

        def execute(self, params: dict[str, Any], context: dict[str, Any]) -> SkillResult:
            return SkillResult(content=f"{name}-{params}", metadata={"name": name})

    return _S()


# ============================================================================
# register / get / exists
# ============================================================================


def test_register_and_get_returns_same_instance():
    reg = SkillRegistry()
    s = _make_skill("alpha")
    reg.register(s)
    assert reg.get("alpha") is s
    assert reg.exists("alpha") is True


def test_get_missing_returns_none():
    reg = SkillRegistry()
    assert reg.get("ghost") is None
    assert reg.exists("ghost") is False


def test_register_duplicate_overwrites_and_warns(caplog):
    """重复注册同名技能 → 覆盖 + 打 WARNING 日志."""
    reg = SkillRegistry()
    s1 = _make_skill("dup")
    s2 = _make_skill("dup")
    reg.register(s1)
    with caplog.at_level("WARNING", logger="backend.skills.registry"):
        reg.register(s2)
    assert reg.get("dup") is s2
    assert any("已存在" in rec.message for rec in caplog.records)


# ============================================================================
# unregister
# ============================================================================


def test_unregister_existing_returns_true():
    reg = SkillRegistry()
    reg.register(_make_skill("temp"))
    assert reg.unregister("temp") is True
    assert reg.get("temp") is None
    assert reg.exists("temp") is False


def test_unregister_missing_returns_false():
    reg = SkillRegistry()
    assert reg.unregister("nope") is False


# ============================================================================
# list / list_names / clear
# ============================================================================


def test_list_returns_schema_objects():
    reg = SkillRegistry()
    s = _make_skill("alpha")
    reg.register(s)
    schemas = reg.list()
    assert len(schemas) == 1
    assert isinstance(schemas[0], SkillSchema)
    assert schemas[0].name == "alpha"


def test_list_names_returns_all_registered_names():
    reg = SkillRegistry()
    reg.register(_make_skill("alpha"))
    reg.register(_make_skill("beta"))
    reg.register(_make_skill("gamma"))
    assert sorted(reg.list_names()) == ["alpha", "beta", "gamma"]


def test_clear_empties_registry():
    reg = SkillRegistry()
    reg.register(_make_skill("a"))
    reg.register(_make_skill("b"))
    reg.clear()
    assert reg.list_names() == []
    assert reg.get("a") is None


# ============================================================================
# match / match_all
# ============================================================================


def test_match_returns_first_skill_whose_triggers_match():
    reg = SkillRegistry()
    reg.register(_make_skill("code", triggers=["写代码", "code"]))
    reg.register(_make_skill("search", triggers=["搜索", "search"]))
    matched = reg.match("请帮我 code review")
    assert matched is not None
    assert matched.name == "code"


def test_match_returns_none_when_no_skill_matches():
    reg = SkillRegistry()
    reg.register(_make_skill("code", triggers=["写代码"]))
    assert reg.match("什么也不相关的输入") is None


def test_match_all_returns_every_matching_skill():
    reg = SkillRegistry()
    # 两个 skill 都有 "code" trigger, 一个有 "search"
    reg.register(_make_skill("code1", triggers=["code", "foo"]))
    reg.register(_make_skill("code2", triggers=["code", "bar"]))
    reg.register(_make_skill("search", triggers=["search"]))
    matched = reg.match_all("please code something")
    names = sorted(s.name for s in matched)
    assert names == ["code1", "code2"]


# ============================================================================
# execute
# ============================================================================


def test_execute_routes_to_matched_skill_and_returns_its_result():
    reg = SkillRegistry()
    s = _make_skill("code", triggers=["code"])
    reg.register(s)
    result = reg.execute("code please", {"x": 1}, {"llm": None})
    assert result is not None
    assert result.success is True
    assert "code" in result.content
    assert result.metadata["name"] == "code"


def test_execute_returns_none_when_no_match():
    reg = SkillRegistry()
    reg.register(_make_skill("code", triggers=["code"]))
    assert reg.execute("nothing matches", {}, {}) is None


def test_execute_wraps_skill_exception_into_failure_result():
    """skill.execute 抛异常时, registry 不向上传播, 而是返回失败 SkillResult."""

    class _BoomSkill(BaseSkill):
        def _build_schema(self) -> SkillSchema:
            return SkillSchema(name="boom", description="always fails", triggers=["boom"])

        def execute(self, params: dict[str, Any], context: dict[str, Any]) -> SkillResult:
            raise RuntimeError("intentional failure")

    reg = SkillRegistry()
    reg.register(_BoomSkill())
    result = reg.execute("boom!", {}, {})
    assert result is not None
    assert result.success is False
    assert "intentional failure" in (result.error or "")
    assert result.content is None


def test_execute_passes_params_and_context_through_to_skill():
    """execute 把 params 和 context 原样转发给 skill."""
    skill = Mock()
    schema = Mock(spec=SkillSchema)
    schema.name = "mock-skill"
    skill.schema = schema
    skill.match.return_value = True
    skill.execute.return_value = SkillResult(content="ok")
    reg = SkillRegistry()
    reg.register(skill)

    ctx = {"llm": Mock(), "tools": {}}
    params = {"action": "write"}
    result = reg.execute("any text", params, ctx)
    assert result is not None
    skill.execute.assert_called_once_with(params, ctx)
