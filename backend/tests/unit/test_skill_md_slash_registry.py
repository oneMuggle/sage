# mypy: disable-error-code="no-untyped-def,attr-defined,func-returns-value"
"""M10 测试: SlashCommandRegistry。

覆盖 backend.skills.skill_md.slash_registry:
- 从 SkillRegistry 索引 user_invocable=true 的 SKILL.md 技能
- resolve(command_name) 返回匹配 skill, None 当未找到
- 接受带或不带前导斜杠的命令名
- list_commands() 返回所有已注册命令名
- user_invocable=false 的技能不索引
- builtin 技能永不索引
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

from backend.skills.registry import SkillRegistry
from backend.skills.skill_md.skill import DispatchMode, SkillMdDocument, SkillMdSkill
from backend.skills.skill_md.slash_registry import SlashCommandRegistry

pytestmark = pytest.mark.unit


# =====================================================================
# helpers
# =====================================================================


def _make_skill(
    name: str,
    *,
    user_invocable: bool = False,
    user_invocable_name: Optional[str] = None,
    command_dispatch: str = "auto",
    script_runner: object = None,
    body_content: Optional[str] = None,
) -> SkillMdSkill:
    """构造 SkillMdSkill 用于测试 (绕过真实 loader)。"""
    doc = SkillMdDocument(
        name=name,
        description=f"Test skill {name}",
        body=body_content if body_content is not None else f"Body of {name}",
        base_dir=Path(f"/tmp/skills/{name}"),
        dispatch=DispatchMode(
            user_invocable=user_invocable,
            user_invocable_name=user_invocable_name,
            command_dispatch=command_dispatch,
        ),
    )
    return SkillMdSkill(doc, base_dir=doc.base_dir, script_runner=script_runner)  # type: ignore[arg-type]


# =====================================================================
# SlashCommandRegistry 索引构建
# =====================================================================


def test_registry_indexes_skill_with_user_invocable_true():
    """user_invocable=true 的 SKILL.md 技能被索引。"""
    registry = SkillRegistry()
    skill = _make_skill("review", user_invocable=True, user_invocable_name="/review")
    registry.register(skill)

    slash = SlashCommandRegistry.from_registry(registry)

    assert slash.resolve("/review") is skill
    assert slash.resolve("review") is skill  # 不带前导斜杠也接受


def test_registry_skips_skill_with_user_invocable_false():
    """user_invocable=false 的 SKILL.md 技能不索引。"""
    registry = SkillRegistry()
    skill = _make_skill("body-only", user_invocable=False)
    registry.register(skill)

    slash = SlashCommandRegistry.from_registry(registry)

    assert slash.resolve("body-only") is None
    assert slash.resolve("/body-only") is None


def test_registry_skips_non_skillmd_skill():
    """非 SkillMdSkill（即 builtin 技能）不索引。"""
    registry = SkillRegistry()

    # 模拟 builtin: 非 SkillMdSkill 实例
    builtin = MagicMock()
    builtin.name = "search"
    # 关键: 不是 SkillMdSkill 实例
    registry.register(builtin)

    slash = SlashCommandRegistry.from_registry(registry)

    assert slash.resolve("/search") is None
    assert slash.resolve("search") is None


def test_registry_returns_none_for_unknown_command():
    """未知命令 → None。"""
    registry = SkillRegistry()
    slash = SlashCommandRegistry.from_registry(registry)

    assert slash.resolve("/unknown") is None


# =====================================================================
# list_commands
# =====================================================================


def test_list_commands_returns_all_registered():
    """list_commands 返回所有已注册命令名(带前导斜杠)。"""
    registry = SkillRegistry()
    registry.register(_make_skill("review", user_invocable=True, user_invocable_name="/review"))
    registry.register(_make_skill("commit", user_invocable=True, user_invocable_name="/commit"))

    slash = SlashCommandRegistry.from_registry(registry)

    commands = slash.list_commands()
    assert set(commands) == {"/review", "/commit"}


def test_list_commands_empty_when_no_user_invocable():
    """无 user_invocable 技能时, list_commands 返回空列表。"""
    registry = SkillRegistry()
    registry.register(_make_skill("body-only", user_invocable=False))

    slash = SlashCommandRegistry.from_registry(registry)

    assert slash.list_commands() == []


# =====================================================================
# resolve edge cases
# =====================================================================


def test_resolve_normalizes_leading_slash():
    """resolve 接受 "/foo" 和 "foo", 视作同一命令。"""
    registry = SkillRegistry()
    skill = _make_skill("review", user_invocable=True, user_invocable_name="/review")
    registry.register(skill)

    slash = SlashCommandRegistry.from_registry(registry)

    assert slash.resolve("/review") is skill
    assert slash.resolve("review") is skill


def test_resolve_empty_returns_none():
    """resolve 空字符串 → None。"""
    registry = SkillRegistry()
    slash = SlashCommandRegistry.from_registry(registry)

    assert slash.resolve("") is None
    assert slash.resolve("/") is None


def test_resolve_multiple_slashes_normalized():
    """带多个前导斜杠的命令也规范化。"""
    registry = SkillRegistry()
    skill = _make_skill("review", user_invocable=True, user_invocable_name="/review")
    registry.register(skill)

    slash = SlashCommandRegistry.from_registry(registry)

    # "//review" 视作 "/review" (normalize 内部处理)
    assert slash.resolve("//review") is skill


# =====================================================================
# execute_command - 委托 SkillMdSkill.execute_v2 (v1 body fallback 路径)
# =====================================================================


@pytest.mark.asyncio()
async def test_execute_command_returns_skill_body():
    """execute_command → 调 SkillMdSkill.execute_v2 (v1 body fallback 路径)。

    设计: slash command 触发后,默认行为是返回 SKILL.md body 作为
    system prompt 模板,不直接执行脚本。脚本执行仍走 POST /skills/{name}/execute
    with 显式 'script' 参数。
    """
    registry = SkillRegistry()
    skill = _make_skill(
        "review",
        user_invocable=True,
        user_invocable_name="/review",
        body_content="You are a careful reviewer.",
    )
    registry.register(skill)

    slash = SlashCommandRegistry.from_registry(registry)
    result = await slash.execute_command("/review", args=("file.py",))

    # 返回的是 body, 供 chat 层注入 system prompt
    assert result.success is True
    assert "reviewer" in str(result.content)


@pytest.mark.asyncio()
async def test_execute_command_unknown_command_raises():
    """execute_command 对未知命令 → 抛 LookupError (路由层转 404)。"""
    registry = SkillRegistry()
    slash = SlashCommandRegistry.from_registry(registry)

    with pytest.raises(LookupError) as exc:
        await slash.execute_command("/unknown", args=())
    assert "unknown" in str(exc.value).lower()
