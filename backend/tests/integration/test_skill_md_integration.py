"""SKILL.md 适配层端到端集成测试。

通过 ``InprocSkillAdapter`` 全链路验证:
- list 包含 builtin + SKILL.md
- SKILL.md execute 返回的 content / metadata 正确
- toggle 状态独立
- disabled 时 execute 返 success=False
"""

from __future__ import annotations

import asyncio
import os
import unittest.mock
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _write_skill_md(tmp_path: Path, name: str, body: str = "Skill body\n") -> Path:
    """在 tmp_path/<name>/SKILL.md 写一个合法 SKILL.md。"""
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        f"---\n"
        f"name: {name}\n"
        f"description: test {name}\n"
        f"version: 0.1.0\n"
        f"---\n"
        f"{body}",
        encoding="utf-8",
    )
    return path


def _write_skill_md_with_dispatch(
    tmp_path: Path,
    name: str,
    *,
    user_invocable: bool = False,
    user_invocable_name: str | None = None,
    command_dispatch: str = "auto",
    disable_model_invocation: bool = False,
    body: str = "Skill body\n",
) -> Path:
    """写带 v2 dispatch frontmatter 的 SKILL.md (M9 测试用)。"""
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    extra_lines: list[str] = []
    if user_invocable:
        extra_lines.append("user-invocable: true")
    if user_invocable_name is not None:
        extra_lines.append(f"user-invocable-name: {user_invocable_name}")
    if command_dispatch != "auto":
        extra_lines.append(f"command-dispatch: {command_dispatch}")
    if disable_model_invocation:
        extra_lines.append("disable-model-invocation: true")
    extra_block = ("\n" + "\n".join(extra_lines)) if extra_lines else ""
    path.write_text(
        f"---\n"
        f"name: {name}\n"
        f"description: test {name}\n"
        f"version: 0.1.0{extra_block}\n"
        f"---\n"
        f"{body}",
        encoding="utf-8",
    )
    return path


def _build_adapter_with_skillmd(tmp_path: Path, name: str, body: str = "Skill body\n"):
    """构造 InprocSkillAdapter 并在 tmp_path 加载一个 SKILL.md。

    注: M9 测试需要自定义 frontmatter (dispatch 字段),请直接用
    ``_build_adapter_with_skillmd_path()`` 或先写文件再调本函数。
    本函数保留默认 body 用于简单场景。
    """
    from backend.adapters.out.skill import InprocSkillAdapter
    from backend.skills import register_all_skills, register_skill_md_skills
    from backend.skills.registry import SkillRegistry

    _write_skill_md(tmp_path, name, body)
    registry = SkillRegistry()
    register_all_skills(registry)
    register_skill_md_skills(registry, dirs=[str(tmp_path)])
    adapter = InprocSkillAdapter.__new__(InprocSkillAdapter)
    adapter._registry = registry
    adapter._enabled = {}
    adapter._usage_count = {}
    return adapter


def _build_adapter_from_existing(tmp_path: Path) -> "InprocSkillAdapter":  # noqa: F821
    """从已存在 SKILL.md 的 tmp_path 构造 adapter (不重写文件)。

    用于 M9 测试: caller 先用 ``_write_skill_md_with_dispatch`` 写好文件,
    再调本函数构造 adapter 以保留 dispatch frontmatter。
    """
    from backend.adapters.out.skill import InprocSkillAdapter
    from backend.skills import register_all_skills, register_skill_md_skills
    from backend.skills.registry import SkillRegistry

    registry = SkillRegistry()
    register_all_skills(registry)
    register_skill_md_skills(registry, dirs=[str(tmp_path)])
    adapter = InprocSkillAdapter.__new__(InprocSkillAdapter)
    adapter._registry = registry
    adapter._enabled = {}
    adapter._usage_count = {}
    return adapter


# =====================================================================
# InprocSkillAdapter 端到端
# =====================================================================


def test_adapter_lists_builtins_plus_skillmd(tmp_path):
    """InprocSkillAdapter 启动后同时包含 builtin 与 SKILL.md。"""
    adapter = _build_adapter_with_skillmd(tmp_path, "alpha")
    names = set(adapter._registry.list_names())
    assert {"search", "writer", "coder", "travel"} <= names
    assert "alpha" in names


def test_adapter_extended_serialization_for_skillmd(tmp_path):
    """list_skills_extended 为 SKILL.md 技能输出 source/body/base_dir/version。"""
    adapter = _build_adapter_with_skillmd(tmp_path, "alpha", body="my body")
    items = adapter.list_skills_extended()
    by_name = {item["name"]: item for item in items}

    # builtin 不输出扩展字段
    builtin = by_name["search"]
    assert builtin["source"] == "builtin"
    assert "body" not in builtin
    assert "base_dir" not in builtin
    assert "version" not in builtin

    # SKILL.md 输出全部扩展字段
    skillmd = by_name["alpha"]
    assert skillmd["source"] == "skillmd"
    assert skillmd["body"] == "my body"
    assert skillmd["base_dir"] == str(tmp_path / "alpha")
    assert skillmd["version"] == "0.1.0"


def test_adapter_execute_skillmd_returns_body_and_metadata(tmp_path):
    """SKILL.md execute 返回 body 字符串 + metadata 含 source。"""
    adapter = _build_adapter_with_skillmd(tmp_path, "alpha", body="special body content")
    result = asyncio.run(adapter.execute("alpha", action="", args={}))
    assert result.success is True
    assert result.content == "special body content"
    assert result.metadata["source"] == "skillmd"
    assert result.metadata["name"] == "alpha"
    assert result.metadata["version"] == "0.1.0"


def test_adapter_toggle_skillmd_persists(tmp_path):
    """SKILL.md 技能 toggle 后 is_enabled 状态正确。"""
    adapter = _build_adapter_with_skillmd(tmp_path, "alpha")
    assert adapter.is_enabled("alpha") is True
    assert adapter.set_enabled("alpha", False) is True
    assert adapter.is_enabled("alpha") is False
    assert adapter.set_enabled("alpha", True) is True
    assert adapter.is_enabled("alpha") is True


def test_adapter_disabled_skillmd_execute_returns_error(tmp_path):
    """SKILL.md 技能被 set_enabled(False) 后, execute 返 success=False。"""
    adapter = _build_adapter_with_skillmd(tmp_path, "alpha")
    adapter.set_enabled("alpha", False)
    result = asyncio.run(adapter.execute("alpha", action="", args={}))
    assert result.success is False
    assert "disabled" in (result.error or "")


def test_adapter_collision_with_builtin_skillmd_skipped(tmp_path):
    """当 SKILL.md 与 builtin 同名, builtin 胜, SKILL.md 被 skip。"""
    from backend.skills import register_all_skills, register_skill_md_skills
    from backend.skills.registry import SkillRegistry

    _write_skill_md(tmp_path, "search", body="hijack attempt")
    registry = SkillRegistry()
    register_all_skills(registry)
    loaded = register_skill_md_skills(registry, dirs=[str(tmp_path)])
    assert loaded == 0  # 冲突, 未加载

    builtin = registry.get("search")
    assert builtin is not None
    result = builtin.execute(params={}, context={})
    assert result.content != "hijack attempt"


def test_adapter_no_skillmd_dirs_does_not_break(tmp_path):
    """当 SAGE_SKILLS_DIR / cwd/skills / ~/.sage/skills 都不存在时, adapter 仍能启动。"""
    env_dir = tmp_path / "no-skills"
    with unittest.mock.patch.dict(os.environ, {"SAGE_SKILLS_DIR": str(env_dir)}, clear=False):
        # 用 tmp_path 作为 cwd, 避免 cwd/skills 干扰
        old_cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            from backend.adapters.out.skill import InprocSkillAdapter

            adapter = InprocSkillAdapter()
            names = set(adapter._registry.list_names())
            assert {"search", "writer", "coder", "travel"} <= names
        finally:
            os.chdir(old_cwd)


# =====================================================================
# M9: DispatchMode 元数据序列化
# =====================================================================


def test_adapter_extended_includes_dispatch_defaults_for_skillmd(tmp_path):
    """SKILL.md 无 dispatch 字段时, 序列化输出 default DispatchMode（嵌套 dispatch dict）。"""
    adapter = _build_adapter_with_skillmd(tmp_path, "alpha")
    items = adapter.list_skills_extended()
    alpha = next(i for i in items if i["name"] == "alpha")

    assert "dispatch" in alpha
    assert alpha["dispatch"] == {
        "disable_model_invocation": False,
        "user_invocable": False,
        "user_invocable_name": None,
        "command_dispatch": "auto",
    }


def test_adapter_extended_includes_dispatch_custom_values(tmp_path):
    """SKILL.md 自定义 dispatch 字段 → 序列化输出对应值。"""
    _write_skill_md_with_dispatch(
        tmp_path,
        "alpha",
        user_invocable=True,
        user_invocable_name="/review",
        command_dispatch="tool",
        disable_model_invocation=True,
    )
    adapter = _build_adapter_from_existing(tmp_path)
    items = adapter.list_skills_extended()
    alpha = next(i for i in items if i["name"] == "alpha")

    assert alpha["dispatch"] == {
        "disable_model_invocation": True,
        "user_invocable": True,
        "user_invocable_name": "/review",
        "command_dispatch": "tool",
    }


def test_adapter_extended_omits_dispatch_for_builtin(tmp_path):
    """builtin 技能（无 v2 dispatch）→ 不输出 dispatch key（TS strict optional 兼容）。"""
    from backend.adapters.out.skill import InprocSkillAdapter

    # 用全 builtin adapter (没有 SKILL.md 加载)
    env_dir = tmp_path / "no-skills"
    with unittest.mock.patch.dict(os.environ, {"SAGE_SKILLS_DIR": str(env_dir)}, clear=False):
        old_cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            adapter = InprocSkillAdapter()
            items = adapter.list_skills_extended()
            search = next(i for i in items if i["name"] == "search")
            assert "dispatch" not in search
        finally:
            os.chdir(old_cwd)
