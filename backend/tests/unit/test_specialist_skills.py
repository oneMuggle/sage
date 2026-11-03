# mypy: disable-error-code="no-untyped-def,attr-defined"
"""M1-C — 专家私有技能目录（spec §5.2）测试。

覆盖:

1. ``backend.skills.specialist_skills`` 纯函数 — 目录发现 / agent_id 校验 /
   私有技能名解析 / 允许集合并与同名遮蔽
2. ``InprocSkillAdapter`` 私有 loader 集成 — ``SAGE_SPECIALISTS_DIR`` 下
   各专家 ``skills/`` 注册为 ``specialist__<agent_id>__<name>``；默认遮罩；
   owner 允许集并入本人私有技能；rescan 注销已删除目录
3. ``SkillTool`` — 无作用域时私有技能按"未知技能"处理，owner 作用域内可执行
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from backend.skills.specialist_skills import (
    SPECIALIST_SKILL_PREFIX,
    agent_id_from_private_skill,
    discover_specialist_skill_dirs,
    is_agent_id_safe,
    resolve_specialist_allowlist,
    skill_name_prefix,
    specialists_root,
)

pytestmark = pytest.mark.unit

WRITER_PRIVATE = "specialist__writer__polish-prose"
CODER_PRIVATE = "specialist__coder__scan-repo"


# =====================================================================
# helpers
# =====================================================================


def _write_skill_md(skill_dir: Path, name: str, body: str = "# body\n") -> Path:
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: test {name}\n"
        "user-invocable: true\n"
        "---\n" + body,
        encoding="utf-8",
    )
    return path


def _write_private_skill(
    root: Path, agent_id: str, name: str, body: str = "# body\n"
) -> Path:
    return _write_skill_md(root / agent_id / "skills" / name, name, body)


def _write_global_skill(tmp_path: Path, name: str, body: str = "# body\n") -> Path:
    return _write_skill_md(tmp_path / name, name, body)


def _make_adapter(tmp_path: Path):
    """装了两个全局技能的 InprocSkillAdapter；私有技能由 env fixture 提供。"""
    from backend.adapters.out.skill.inproc import InprocSkillAdapter
    from backend.skills.registry import SkillRegistry
    from backend.skills.skill_md.loader import SkillMdHotLoader

    _write_global_skill(tmp_path, "zz-write-report", "# Write report body\n")
    _write_global_skill(tmp_path, "zz-code-review", "# Code review body\n")
    registry = SkillRegistry()
    SkillMdHotLoader(registry, [tmp_path]).scan_and_load()
    return InprocSkillAdapter(registry=registry)


@pytest.fixture()
def specialists_dir(tmp_path, monkeypatch):
    root = tmp_path / "specialists"
    root.mkdir()
    monkeypatch.setenv("SAGE_SPECIALISTS_DIR", str(root))
    return root


# =====================================================================
# 1. 纯函数
# =====================================================================


class TestAgentIdFromPrivateSkill:
    def test_parses_owner(self):
        assert agent_id_from_private_skill(WRITER_PRIVATE) == "writer"

    def test_global_skill_is_none(self):
        assert agent_id_from_private_skill("write-report") is None

    @pytest.mark.parametrize(
        "name",
        [
            "specialist__writer",
            "specialist____review",
            "specialist__writer__",
            "specialist__",
        ],
    )
    def test_malformed_is_none(self, name):
        assert agent_id_from_private_skill(name) is None


class TestIsAgentIdSafe:
    @pytest.mark.parametrize("agent_id", ["writer", "w-1", "a.b_c", "A" * 64])
    def test_accepts(self, agent_id):
        assert is_agent_id_safe(agent_id) is True

    @pytest.mark.parametrize(
        "agent_id", ["", "../x", "..", ".hidden", "-x", "a/b", "a b", "a" * 65]
    )
    def test_rejects(self, agent_id):
        assert is_agent_id_safe(agent_id) is False


class TestNamesAndRoot:
    def test_skill_name_prefix(self):
        assert skill_name_prefix("writer") == "specialist__writer__"
        assert skill_name_prefix("writer").startswith(SPECIALIST_SKILL_PREFIX)

    def test_specialists_root_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SAGE_SPECIALISTS_DIR", str(tmp_path))
        assert specialists_root() == tmp_path

    def test_specialists_root_default(self, monkeypatch):
        monkeypatch.delenv("SAGE_SPECIALISTS_DIR", raising=False)
        assert specialists_root() == Path.home() / ".sage" / "specialists"


class TestDiscoverSpecialistSkillDirs:
    def test_missing_root_is_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SAGE_SPECIALISTS_DIR", str(tmp_path / "nope"))
        assert discover_specialist_skill_dirs() == []

    def test_discovers_each_agent_skills_dir(self, specialists_dir):
        _write_private_skill(specialists_dir, "writer", "polish-prose")
        _write_private_skill(specialists_dir, "coder", "scan-repo")

        found = dict(discover_specialist_skill_dirs())

        assert set(found) == {"writer", "coder"}
        assert found["writer"] == specialists_dir / "writer" / "skills"

    def test_skips_hidden_invalid_and_skillless(self, specialists_dir):
        _write_private_skill(specialists_dir, "writer", "polish-prose")
        _write_private_skill(specialists_dir, ".hidden", "x")
        _write_private_skill(specialists_dir, "bad id", "x")
        (specialists_dir / "empty").mkdir()

        found = dict(discover_specialist_skill_dirs())

        assert set(found) == {"writer"}

    def test_skips_symlinked_agent_dir(self, specialists_dir, tmp_path):
        real = tmp_path / "elsewhere"
        _write_private_skill(real, "writer", "polish-prose")
        try:
            os.symlink(real / "writer", specialists_dir / "writer")
        except (OSError, NotImplementedError):
            pytest.skip("symlink not supported on this platform")

        assert discover_specialist_skill_dirs() == []


class TestResolveSpecialistAllowlist:
    NAMES = ["write-report", "code-review", WRITER_PRIVATE, CODER_PRIVATE]

    def test_unrestricted_includes_public_and_own_private(self):
        resolved = resolve_specialist_allowlist(None, self.NAMES, "writer")
        assert resolved == {"write-report", "code-review", WRITER_PRIVATE}

    def test_unrestricted_without_private_is_none(self):
        assert resolve_specialist_allowlist(None, ["write-report"], "writer") is None

    def test_patterns_gate_own_private_by_short_name(self):
        """``write-*`` 不命中 ``polish-prose`` → 私有技能不入集。"""
        resolved = resolve_specialist_allowlist(
            ["write-*"], self.NAMES, "writer"
        )
        assert resolved == {"write-report"}

    def test_private_short_name_matches_wildcard(self):
        resolved = resolve_specialist_allowlist(
            ["polish-*", "write-*"],
            ["write-report", WRITER_PRIVATE],
            "writer",
        )
        assert resolved == {"write-report", WRITER_PRIVATE}

    def test_other_specialist_private_never_included(self):
        resolved = resolve_specialist_allowlist(None, self.NAMES, "writer")
        assert resolved is not None
        assert CODER_PRIVATE not in resolved

    def test_own_private_shadows_global_same_name(self):
        """spec §5.2「私有 > 全局」：同名时全局技能从允许集移除。"""
        resolved = resolve_specialist_allowlist(
            ["review"],
            ["review", "specialist__writer__review"],
            "writer",
        )
        assert resolved == {"specialist__writer__review"}

    def test_unsafe_agent_id_degrades_to_public_only(self):
        assert (
            resolve_specialist_allowlist(None, ["write-report", WRITER_PRIVATE], "../writer")
            is None
        )


# =====================================================================
# 2. InprocSkillAdapter 私有 loader 集成
# =====================================================================


class TestAdapterPrivateRegistration:
    def test_private_skills_registered_with_prefix(self, tmp_path, specialists_dir):
        _write_private_skill(specialists_dir, "writer", "polish-prose", "# Polish body\n")
        _write_private_skill(specialists_dir, "coder", "scan-repo", "# Scan body\n")

        adapter = _make_adapter(tmp_path)

        names = set(adapter._registry.list_names())
        assert WRITER_PRIVATE in names
        assert CODER_PRIVATE in names

    def test_private_skills_hidden_by_default(self, tmp_path, specialists_dir):
        _write_private_skill(specialists_dir, "writer", "polish-prose")

        adapter = _make_adapter(tmp_path)

        visible = {s.name for s in adapter.list_skills()}
        assert WRITER_PRIVATE not in visible
        assert not any(n.startswith(SPECIALIST_SKILL_PREFIX) for n in visible)

    def test_owner_allowlist_unions_own_private(self, tmp_path, specialists_dir):
        _write_private_skill(specialists_dir, "writer", "polish-prose")
        _write_private_skill(specialists_dir, "coder", "scan-repo")

        adapter = _make_adapter(tmp_path)
        allowed = adapter.resolve_agent_allowlist([], "writer")

        assert allowed is not None
        assert WRITER_PRIVATE in allowed
        assert CODER_PRIVATE not in allowed
        assert "zz-write-report" in allowed

        visible = {s.name for s in adapter.list_skills(allowed=allowed)}
        assert WRITER_PRIVATE in visible
        assert CODER_PRIVATE not in visible

    def test_owner_patterns_gate_private_by_short_name(self, tmp_path, specialists_dir):
        _write_private_skill(specialists_dir, "writer", "polish-prose")
        _write_private_skill(specialists_dir, "coder", "scan-repo")

        adapter = _make_adapter(tmp_path)
        allowed = adapter.resolve_agent_allowlist(["scan-*"], "coder")

        assert allowed == {CODER_PRIVATE}


class TestAdapterPrivateExecution:
    async def test_execute_private_skill_denied_without_scope(
        self, tmp_path, specialists_dir
    ):
        _write_private_skill(specialists_dir, "writer", "polish-prose", "# Polish body\n")

        adapter = _make_adapter(tmp_path)
        result = await adapter.execute(WRITER_PRIVATE, "", {})

        assert result.success is False
        assert result.metadata.get("permission_denied") is True

    async def test_execute_private_skill_allowed_for_owner(
        self, tmp_path, specialists_dir
    ):
        _write_private_skill(specialists_dir, "writer", "polish-prose", "# Polish body\n")

        adapter = _make_adapter(tmp_path)
        allowed = adapter.resolve_agent_allowlist([], "writer")
        result = await adapter.execute(WRITER_PRIVATE, "", {}, allowed=allowed)

        assert result.success is True
        assert "# Polish body" in result.content

    async def test_execute_command_private_denied_for_non_owner(
        self, tmp_path, specialists_dir
    ):
        _write_private_skill(specialists_dir, "writer", "polish-prose")

        adapter = _make_adapter(tmp_path)
        coder_allowed = adapter.resolve_agent_allowlist([], "coder")
        with pytest.raises(LookupError):
            await adapter.execute_command(WRITER_PRIVATE, allowed=coder_allowed)


class TestAdapterPrivateSlashCommands:
    def test_slash_commands_hide_private_by_default(self, tmp_path, specialists_dir):
        _write_private_skill(specialists_dir, "writer", "polish-prose")

        adapter = _make_adapter(tmp_path)

        assert f"/{WRITER_PRIVATE}" not in adapter.list_slash_commands()

    def test_slash_commands_show_own_private_for_owner(
        self, tmp_path, specialists_dir
    ):
        _write_private_skill(specialists_dir, "writer", "polish-prose")
        _write_private_skill(specialists_dir, "coder", "scan-repo")

        adapter = _make_adapter(tmp_path)
        allowed = adapter.resolve_agent_allowlist([], "writer")
        commands = adapter.list_slash_commands(allowed=allowed)

        assert f"/{WRITER_PRIVATE}" in commands
        assert f"/{CODER_PRIVATE}" not in commands


class TestAdapterRescanPrunesRemovedSpecialist:
    def test_rescan_unregisters_removed_specialist(self, tmp_path, specialists_dir):
        _write_private_skill(specialists_dir, "writer", "polish-prose")

        adapter = _make_adapter(tmp_path)
        assert WRITER_PRIVATE in set(adapter._registry.list_names())

        shutil.rmtree(specialists_dir / "writer")
        adapter.rescan_skill_mds()

        assert WRITER_PRIVATE not in set(adapter._registry.list_names())


# =====================================================================
# 3. SkillTool — 私有技能默认遮罩 / owner 可执行
# =====================================================================


class TestSkillToolPrivateScope:
    def test_masks_private_skill_without_scope(self, tmp_path, specialists_dir):
        from backend.tools.skill_tool import SkillTool

        _write_private_skill(specialists_dir, "writer", "polish-prose")
        adapter = _make_adapter(tmp_path)
        tool = SkillTool(adapter=adapter)

        result = tool.execute(skill=WRITER_PRIVATE)

        assert result.success is False
        assert "unknown skill" in (result.error or "")
        # 可用清单不泄漏私有技能名
        assert WRITER_PRIVATE not in (result.error or "").split("available skills:", 1)[-1]

    def test_agent_scope_allows_own_private(self, tmp_path, specialists_dir):
        from backend.tools.skill_tool import SkillTool

        _write_private_skill(
            specialists_dir, "writer", "polish-prose", "# Polish body\n"
        )
        adapter = _make_adapter(tmp_path)
        tool = SkillTool(adapter=adapter, agent_id="writer")

        result = tool.execute(skill=WRITER_PRIVATE)

        assert result.success is True
        assert "# Polish body" in result.content
