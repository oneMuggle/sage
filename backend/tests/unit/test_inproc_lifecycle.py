"""Unit tests for InprocSkillAdapter lifecycle integration（归档 + 分类）。

用 4 个 builtin（search/writer/coder/travel）+ autouse 临时 DB；
reset_skill_adapter 保证 adapter 单例隔离。
"""

import pytest

import backend.adapters.out.skill.inproc as inproc_mod
from backend.adapters.out.skill.inproc import get_singleton


@pytest.fixture()
def adapter(reset_skill_adapter):
    return get_singleton()


def test_set_archived_and_is_archived(adapter):
    assert not adapter.is_archived("search")
    assert adapter.set_archived("search", True) is True
    assert adapter.is_archived("search")


def test_unarchive(adapter):
    adapter.set_archived("search", True)
    assert adapter.set_archived("search", False) is True
    assert not adapter.is_archived("search")


def test_set_enabled_unknown_skill_returns_false(adapter):
    assert adapter.set_enabled("no-such-skill", False) is False


def test_set_enabled_persists_across_adapter_instances(adapter):
    """DB 真相：新 adapter 实例 hydrate 后仍禁用。"""
    adapter.set_enabled("coder", False)
    inproc_mod._skill_adapter_singleton = None
    assert not get_singleton().is_enabled("coder")


def test_hydrate_enabled_ignores_unknown_registry_names(adapter):
    """DB 中孤儿开关不应进入内存缓存。"""
    from backend.skills.lifecycle import get_lifecycle_store

    get_lifecycle_store().set_enabled("no-such-skill", False)
    adapter._hydrate_enabled_from_db()
    assert "no-such-skill" not in adapter._enabled
    assert adapter.is_enabled("no-such-skill") is True


def test_set_archived_unknown_skill_returns_false(adapter):
    assert adapter.set_archived("no-such-skill", True) is False


def test_archive_persists_across_adapter_instances(adapter):
    """DB 真相：新 adapter 实例 hydrate 后仍归档（重启不丢）。"""
    adapter.set_archived("coder", True)
    inproc_mod._skill_adapter_singleton = None  # 强制重建
    assert get_singleton().is_archived("coder")


def test_lifecycle_map_active_stale_archived(adapter):
    adapter.bump_usage("search")  # 刚用 → active
    adapter.set_archived("coder", True)  # → archived
    m = adapter.lifecycle_map()
    assert m["search"] == "active"
    assert m["coder"] == "archived"
    assert m["travel"] == "stale"  # 从未用 → stale
    assert m["writer"] == "stale"


def test_list_skills_extended_includes_lifecycle(adapter):
    adapter.bump_usage("search")
    adapter.set_archived("coder", True)
    ext = {e["name"]: e for e in adapter.list_skills_extended()}
    assert ext["search"]["lifecycle"] == "active"
    assert ext["coder"]["lifecycle"] == "archived"
    assert ext["travel"]["lifecycle"] == "stale"


# ---------- 排除点：auto_activate + slash registry ---------- #


def _skillmd_adapter(
    name, when_to_use="", user_invocable=False, user_invocable_name=None
):
    """构造只含一个 SKILL.md 技能的 adapter（自定义 registry，绕过真实 loader）。"""
    from backend.adapters.out.skill.inproc import InprocSkillAdapter
    from backend.skills.registry import SkillRegistry
    from backend.skills.skill_md.skill import (
        DispatchMode,
        SkillMdDocument,
        SkillMdSkill,
    )

    doc = SkillMdDocument(
        name=name,
        description=f"test {name}",
        when_to_use=when_to_use,
        body=f"body of {name}",
        dispatch=DispatchMode(
            user_invocable=user_invocable,
            user_invocable_name=user_invocable_name,
        ),
    )
    reg = SkillRegistry()
    reg.register(SkillMdSkill(doc))
    return InprocSkillAdapter(registry=reg)


def test_auto_activate_excludes_archived():
    """归档的 SKILL.md 技能不出现在 auto_activate 命中；unarchive 恢复。"""
    adapter = _skillmd_adapter("deploy-skill", when_to_use='"deploy"')
    assert "deploy-skill" in adapter.auto_activate("please deploy now").names
    adapter.set_archived("deploy-skill", True)
    assert "deploy-skill" not in adapter.auto_activate("please deploy now").names
    adapter.set_archived("deploy-skill", False)
    assert "deploy-skill" in adapter.auto_activate("please deploy now").names


def test_slash_list_excludes_archived():
    """归档的 user_invocable 技能不出现在 list_slash_commands。"""
    adapter = _skillmd_adapter("review", user_invocable=True, user_invocable_name="/review")
    assert "/review" in adapter.list_slash_commands()
    adapter.set_archived("review", True)
    assert "/review" not in adapter.list_slash_commands()


@pytest.mark.asyncio()
async def test_disabled_slash_command_is_hidden_and_rejected():
    adapter = _skillmd_adapter("review", user_invocable=True, user_invocable_name="/review")
    adapter.set_enabled("review", False)
    assert "/review" not in adapter.list_slash_commands()
    with pytest.raises(LookupError):
        await adapter.execute_command("/review")


@pytest.mark.asyncio()
async def test_slash_execute_archived_raises():
    """归档技能的 slash command 执行抛 LookupError（路由层 → 404）。"""
    adapter = _skillmd_adapter("review", user_invocable=True, user_invocable_name="/review")
    adapter.set_archived("review", True)
    with pytest.raises(LookupError):
        await adapter.execute_command("/review")
