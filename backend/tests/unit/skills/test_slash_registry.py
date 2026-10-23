"""R128 — slash command 注册表单元测试。

覆盖：from_registry 索引规则（builtin 排除 / user_invocable 过滤 /
显式命名优先 / fallback /{name}）、命令名规范化变体解析、list_commands、
execute_command 委托契约与未注册 LookupError、不可变索引语义。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.skills.skill_md.skill import SkillMdSkill
from backend.skills.skill_md.slash_registry import SlashCommandRegistry

pytestmark = pytest.mark.unit


class _FakeSkillMd(SkillMdSkill):
    """最小替身：只设 _doc，通过 isinstance 门禁，不依赖解析器。"""

    def __init__(self, doc):
        self._doc = doc
        self.execute_calls = []

    async def execute_v2(self, params=None, context=None):
        self.execute_calls.append({"params": params, "context": context})
        return f"body-of-{self._doc.name}"


class _FakeBuiltin:
    """非 SkillMdSkill 的内置技能替身，必须被索引排除。"""


def _doc(name, user_invocable=True, custom_name=None):
    return SimpleNamespace(
        name=name,
        dispatch=SimpleNamespace(
            user_invocable=user_invocable, user_invocable_name=custom_name
        ),
    )


def _registry(skills):
    """duck-typed SkillRegistry：list() 惰性读取 + get(name)。"""

    def list_schemas():
        return [SimpleNamespace(name=s._doc.name) for s in skills]

    def get(name):
        for s in skills:
            if s._doc.name == name:
                return s
        return None

    return SimpleNamespace(list=list_schemas, get=get)


def _md(name, **kw):
    return _FakeSkillMd(_doc(name, **kw))


# ---------------------------------------------------------------------------
# from_registry 索引规则
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_builtin_skills_never_indexed():
    builtin = _FakeBuiltin()
    builtin._doc = _doc("builtin-skill")  # 名字有 _doc 但类型不对
    registry = _registry([builtin])
    reg = SlashCommandRegistry.from_registry(registry)
    assert reg.resolve("/builtin-skill") is None


def test_non_user_invocable_skipped():
    reg = SlashCommandRegistry.from_registry(_registry([_md("hidden", user_invocable=False)]))
    assert reg.resolve("/hidden") is None
    assert reg.list_commands() == []


def test_user_invocable_indexed_with_fallback_name():
    reg = SlashCommandRegistry.from_registry(_registry([_md("weather")]))
    assert reg.resolve("/weather") is not None
    assert reg.list_commands() == ["/weather"]


def test_explicit_invocable_name_preferred():
    skill = _FakeSkillMd(_doc("weather", custom_name="/天气"))
    reg = SlashCommandRegistry.from_registry(_registry([skill]))
    assert reg.resolve("/天气") is skill
    assert reg.resolve("/weather") is None  # fallback 名不注册


def test_registry_get_missing_safe():
    registry = SimpleNamespace(list=lambda: [SimpleNamespace(name="ghost")], get=lambda n: None)
    reg = SlashCommandRegistry.from_registry(registry)
    assert reg.list_commands() == []


# ---------------------------------------------------------------------------
# resolve 规范化
# ---------------------------------------------------------------------------


def test_resolve_accepts_slash_variants():
    skill = _md("foo")
    reg = SlashCommandRegistry.from_registry(_registry([skill]))
    assert reg.resolve("/foo") is skill
    assert reg.resolve("foo") is skill
    assert reg.resolve("//foo") is skill


def test_resolve_unknown_and_empty():
    reg = SlashCommandRegistry.from_registry(_registry([_md("foo")]))
    assert reg.resolve("/bar") is None
    assert reg.resolve("") is None
    assert reg.resolve("///") is None


def test_list_commands_normalized():
    skill = _FakeSkillMd(_doc("a", custom_name="/cmd-a"))
    reg = SlashCommandRegistry.from_registry(_registry([skill]))
    assert reg.list_commands() == ["/cmd-a"]


# ---------------------------------------------------------------------------
# execute_command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_execute_command_delegates_to_execute_v2():
    skill = _md("deploy")
    reg = SlashCommandRegistry.from_registry(_registry([skill]))
    out = await reg.execute_command("/deploy", ("prod", "--fast"))
    assert out == "body-of-deploy"
    assert skill.execute_calls == [
        {"params": {"args": ["prod", "--fast"]}, "context": {}}
    ]


@pytest.mark.asyncio()
async def test_execute_command_unknown_raises_lookup_error():
    reg = SlashCommandRegistry.from_registry(_registry([]))
    with pytest.raises(LookupError, match="not registered"):
        await reg.execute_command("/nope")


# ---------------------------------------------------------------------------
# 不可变索引
# ---------------------------------------------------------------------------


def test_from_registry_is_immutable_snapshot():
    """from_registry 一次性构建：注册表事后新增技能不反映到已建索引。"""
    skills = [_md("foo")]
    registry = _registry(skills)
    reg = SlashCommandRegistry.from_registry(registry)
    assert reg.resolve("/foo") is not None

    skills.append(_md("bar"))  # registry 上新增技能
    registry_list_now = registry.list()
    assert any(s.name == "bar" for s in registry_list_now)  # 源已变化
    assert reg.resolve("/bar") is None  # 已建索引不反映（需重建）
