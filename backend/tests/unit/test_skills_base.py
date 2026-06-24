"""
Skill 基类单元测试

覆盖：
- SkillResult.to_dict() 正常 + 含 error + 空 metadata
- BaseSkill 子类化（_build_schema / execute 抽象）
- schema 懒加载（首次访问才构建）
- name / description / triggers 属性代理
- match() 大小写不敏感 + 部分匹配
- __repr__ 输出
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.skills.base import BaseSkill, SkillResult, SkillSchema

pytestmark = pytest.mark.unit


# ============================================================================
# SkillResult
# ============================================================================


def test_skill_result_to_dict_omits_error_when_none():
    """error 为 None 时, to_dict 不输出 error 字段."""
    result = SkillResult(content="ok", metadata={"k": "v"}, success=True)
    out = result.to_dict()
    assert out == {"success": True, "content": "ok", "metadata": {"k": "v"}}
    assert "error" not in out


def test_skill_result_to_dict_includes_error_when_set():
    """error 非空时, to_dict 输出 error 字段."""
    result = SkillResult(success=False, error="boom")
    out = result.to_dict()
    assert out["success"] is False
    assert out["error"] == "boom"
    assert out["content"] is None
    assert out["metadata"] == {}


def test_skill_result_default_values():
    """默认值: success=True, content=None, metadata={}, error=None."""
    result = SkillResult()
    assert result.success is True
    assert result.content is None
    assert result.metadata == {}
    assert result.error is None


# ============================================================================
# Test helper
# ============================================================================


class _DummySkill(BaseSkill):
    """最小可用技能实现（用于测试基类行为）"""

    def __init__(self, triggers: list[str] | None = None, name: str = "dummy"):
        super().__init__()
        self._triggers = triggers or ["dummy"]
        self._name = name

    def _build_schema(self) -> SkillSchema:
        return SkillSchema(
            name=self._name,
            description="dummy skill",
            triggers=self._triggers,
            parameters={"type": "object", "properties": {}, "required": []},
            examples=["do dummy thing"],
        )

    def execute(self, params: dict[str, Any], context: dict[str, Any]) -> SkillResult:
        return SkillResult(content="done", metadata={"params": params})


class _SchemaBuildCounter(BaseSkill):
    """每次 _build_schema 被调用时计数"""

    call_count = 0

    def __init__(self):
        super().__init__()

    def _build_schema(self) -> SkillSchema:
        type(self).call_count += 1
        return SkillSchema(name="counter", description="counter skill", triggers=["counter"])

    def execute(self, params: dict[str, Any], context: dict[str, Any]) -> SkillResult:
        return SkillResult()


# ============================================================================
# BaseSkill 抽象
# ============================================================================


def test_base_skill_is_abstract_cannot_instantiate_directly():
    """BaseSkill 本身是 ABC, 不能直接实例化."""
    with pytest.raises(TypeError):
        BaseSkill()  # type: ignore[abstract]


def test_base_skill_subclass_must_implement_abstract_methods():
    """只实现部分抽象方法仍不能实例化."""

    class _Partial(BaseSkill):
        def _build_schema(self) -> SkillSchema:
            return SkillSchema(name="p", description="p")

        # execute 故意不实现

    with pytest.raises(TypeError):
        _Partial()  # type: ignore[abstract]


# ============================================================================
# schema 懒加载
# ============================================================================


def test_schema_is_built_lazily_on_first_access():
    """_schema 在首次访问时构造, 之后复用同一实例."""
    _SchemaBuildCounter.call_count = 0
    skill = _SchemaBuildCounter()

    assert skill._schema is None
    assert _SchemaBuildCounter.call_count == 0

    s1 = skill.schema
    assert _SchemaBuildCounter.call_count == 1

    s2 = skill.schema
    assert _SchemaBuildCounter.call_count == 1  # 不再调用
    assert s1 is s2


# ============================================================================
# 属性代理
# ============================================================================


def test_name_description_triggers_proxy_to_schema():
    """name/description/triggers 都代理到 schema 的对应字段."""
    skill = _DummySkill(name="alpha", triggers=["help", "run"])
    assert skill.name == "alpha"
    assert skill.description == "dummy skill"
    assert skill.triggers == ["help", "run"]


# ============================================================================
# match method
# ============================================================================


def test_match_substring_case_insensitive():
    """match() 大小写不敏感, 子串匹配即视为命中."""
    skill = _DummySkill(triggers=["WriteCode", "Debug"])
    assert skill.match("please writecode for me") is True
    assert skill.match("DEBUG this please") is True
    assert skill.match("nothing here") is False


def test_match_returns_false_for_empty_triggers():
    """triggers 为空时, match 永远返回 False."""
    skill = _DummySkill(triggers=[])
    assert skill.match("anything") is False
    assert skill.match("") is False


# ============================================================================
# __repr__
# ============================================================================


def test_repr_contains_class_name_and_skill_name_and_triggers():
    """__repr__ 输出包含类名、skill name 和 triggers 列表."""
    skill = _DummySkill(name="alpha", triggers=["x", "y"])
    r = repr(skill)
    assert "_DummySkill" in r
    assert "alpha" in r
    assert "['x', 'y']" in r
