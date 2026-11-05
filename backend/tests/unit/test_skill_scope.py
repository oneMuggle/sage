# mypy: disable-error-code="no-untyped-def,attr-defined"
"""M1-B — 专家技能允许集（spec §5.1）单元测试。

验收标准（spec §9）::

    同一全局技能库下，写作专家看不到编码技能；非法技能名无法执行。

覆盖四层:

1. ``backend.domain.skill_scope`` 纯函数 — None/空 → 不受限，
   字面名 / ``*`` 前缀展开，``is_skill_allowed`` 语义
2. ``InprocSkillAdapter`` 六个入口的 ``allowed`` 过滤
   （list / list_extended / auto_activate / execute / execute_command /
   list_slash_commands）
3. ``SkillTool`` — ``skill_patterns`` 注入后越权技能按"未知技能"报错，
   可用清单不泄漏越权技能名
4. ``ChatService._skill_activation_block`` — ``allowed`` 透传到 auto_activate
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.application.services.chat_service import _skill_activation_block
from backend.domain.skill_scope import is_skill_allowed, resolve_skill_allowlist
from backend.skills.registry import SkillRegistry
from backend.skills.skill_md.loader import SkillMdHotLoader
from backend.tools.registry import ToolRegistry
from backend.tools.skill_tool import SkillTool, inject_skill_scope

pytestmark = pytest.mark.unit


# =====================================================================
# helpers
# =====================================================================


def _write_skill_md(
    parent: Path,
    name: str,
    when_to_use: str = "",
    body: str = "Body content\n",
) -> Path:
    """在 parent/<name>/SKILL.md 写一个合法 SKILL.md, 返回路径。"""
    skill_dir = parent / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    frontmatter_extra = f'when_to_use: "{when_to_use}"\n' if when_to_use else ""
    # user-invocable: true → 注册为 slash command（入口 3 覆盖需要）
    path.write_text(
        f"---\n"
        f"name: {name}\n"
        f"description: test {name}\n"
        f"user-invocable: true\n"
        f"{frontmatter_extra}"
        f"---\n"
        f"{body}",
        encoding="utf-8",
    )
    return path


def _make_adapter(tmp_path: Path):
    """构造装了一个写作技能 + 一个编码技能的 InprocSkillAdapter。

    与验收场景同构：同一全局技能库，专家只允许 ``write-*``。
    """
    from backend.adapters.out.skill.inproc import InprocSkillAdapter

    _write_skill_md(
        tmp_path,
        "zz-write-report",
        when_to_use="write zz report",
        body="# Write report body\n",
    )
    _write_skill_md(
        tmp_path,
        "zz-code-review",
        when_to_use="review zz code",
        body="# Code review body\n",
    )
    registry = SkillRegistry()
    SkillMdHotLoader(registry, [tmp_path]).scan_and_load()
    return InprocSkillAdapter(registry=registry)


WRITER_ALLOWED = {"zz-write-report"}


# =====================================================================
# 1. 纯函数 — resolve_skill_allowlist / is_skill_allowed
# =====================================================================


class TestResolveSkillAllowlist:
    def test_none_is_unrestricted(self):
        assert resolve_skill_allowlist(None, ["a", "b"]) is None

    def test_empty_and_blank_is_unrestricted(self):
        """非 None 但无有效条目 → 视为未配置，不受限。"""
        assert resolve_skill_allowlist([], ["a", "b"]) is None
        assert resolve_skill_allowlist(["", "   "], ["a", "b"]) is None

    def test_literal_names(self):
        assert resolve_skill_allowlist(["a", "b"], ["a", "b", "c"]) == {"a", "b"}

    def test_wildcard_prefix_expansion(self):
        """``*`` 后缀按注册表里的名字做前缀展开。"""
        resolved = resolve_skill_allowlist(
            ["zz-write-*"], ["zz-write-report", "zz-write-email", "zz-code-review"]
        )
        assert resolved == {"zz-write-report", "zz-write-email"}

    def test_wildcard_no_match_is_empty_set(self):
        """通配无匹配 → 空集合（仍然 fail-closed，不是 None）。"""
        assert resolve_skill_allowlist(["nope-*"], ["a", "b"]) == set()

    def test_literal_names_survive_without_registry_match(self):
        """字面名不依赖注册表 —— 用于"先配允许集，技能后装"的场景。"""
        assert resolve_skill_allowlist(["future-skill"], ["a"]) == {"future-skill"}


class TestIsSkillAllowed:
    def test_none_always_allows(self):
        assert is_skill_allowed(None, "anything") is True

    def test_membership(self):
        assert is_skill_allowed({"a"}, "a") is True
        assert is_skill_allowed({"a"}, "b") is False


# =====================================================================
# 2. InprocSkillAdapter 六入口 allowed 过滤
# =====================================================================


class TestAdapterListEntrypoints:
    def test_list_skills_filters(self, tmp_path):
        """入口 1：技能清单只含允许集内技能。"""
        adapter = _make_adapter(tmp_path)
        names = {s.name for s in adapter.list_skills(allowed=WRITER_ALLOWED)}
        assert names == {"zz-write-report"}

    def test_list_skills_none_unrestricted(self, tmp_path):
        """无 allowed → 不受限，两个测试技能都可见（注入 registry 仍会装载 shipped 技能）。"""
        adapter = _make_adapter(tmp_path)
        names = {s.name for s in adapter.list_skills()}
        assert {"zz-write-report", "zz-code-review"} <= names

    def test_list_skills_extended_filters(self, tmp_path):
        """入口 1（REST 序列化路径）同样过滤。"""
        adapter = _make_adapter(tmp_path)
        names = {e["name"] for e in adapter.list_skills_extended(allowed=WRITER_ALLOWED)}
        assert names == {"zz-write-report"}


class TestAdapterAutoActivate:
    def test_disallowed_skill_not_activated(self, tmp_path):
        """入口 2：消息命中编码技能，但写作专家不允许 → 不激活。"""
        adapter = _make_adapter(tmp_path)
        result = adapter.auto_activate("please review zz code", allowed=WRITER_ALLOWED)
        assert result.activated is False
        assert "# Code review body" not in result.context_block

    def test_allowed_skill_activated(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        result = adapter.auto_activate("please write zz report", allowed=WRITER_ALLOWED)
        assert result.activated is True
        assert result.names == ("zz-write-report",)


class TestAdapterExecute:
    async def test_disallowed_skill_denied_before_exists(self, tmp_path):
        """入口 4：越权执行被拒绝，且先于存在性检查（不泄漏存在性）。"""
        adapter = _make_adapter(tmp_path)
        result = await adapter.execute("zz-code-review", "", {}, allowed=WRITER_ALLOWED)
        assert result.success is False
        assert "not permitted" in (result.error or "")
        assert result.metadata.get("permission_denied") is True

    async def test_unknown_skill_under_allowlist_reports_not_found(self, tmp_path):
        """允许集内的不存在技能 → 与越权区分开，走存在性检查报 not found。"""
        adapter = _make_adapter(tmp_path)
        result = await adapter.execute("ghost", "", {}, allowed={"ghost"})
        assert result.success is False
        assert "not found" in (result.error or "")
        assert result.metadata.get("permission_denied") is not True

    async def test_allowed_skill_executes(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        result = await adapter.execute("zz-write-report", "", {}, allowed=WRITER_ALLOWED)
        assert result.success is True
        assert "# Write report body" in result.content


class TestAdapterSlashEntrypoints:
    def test_list_slash_commands_filters(self, tmp_path):
        """入口 3a：slash 命令清单不含越权技能。"""
        adapter = _make_adapter(tmp_path)
        commands = adapter.list_slash_commands(allowed=WRITER_ALLOWED)
        assert "/zz-write-report" in commands
        assert "/zz-code-review" not in commands

    async def test_execute_command_disallowed_raises_lookup(self, tmp_path):
        """入口 3b：越权 slash 命令按"未知命令"处理（路由层 → 404）。"""
        adapter = _make_adapter(tmp_path)
        with pytest.raises(LookupError):
            await adapter.execute_command("zz-code-review", allowed=WRITER_ALLOWED)

    async def test_execute_command_allowed_runs(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        result = await adapter.execute_command("zz-write-report", allowed=WRITER_ALLOWED)
        assert result.success is True
        assert "# Write report body" in result.content

    def test_resolve_allowlist_uses_registry_names(self, tmp_path):
        """adapter.resolve_allowlist 以注册表技能名展开通配。"""
        adapter = _make_adapter(tmp_path)
        assert adapter.resolve_allowlist(["zz-write-*"]) == {"zz-write-report"}


# =====================================================================
# 3. SkillTool — skill_patterns 注入
# =====================================================================


class TestSkillToolRestriction:
    def test_disallowed_skill_reports_unknown_with_restricted_listing(self, tmp_path):
        """入口 4（in-loop）：越权技能按"未知技能"报错，清单只列允许集。"""
        adapter = _make_adapter(tmp_path)
        tool = SkillTool(adapter=adapter, skill_patterns=["zz-write-*"])

        result = tool.execute(skill="zz-code-review")

        assert result.success is False
        assert "unknown skill" in (result.error or "")
        # 可用清单只列允许集内的技能
        listing = (result.error or "").split("available skills:", 1)[-1]
        assert "zz-write-report" in listing
        assert "zz-code-review" not in listing

    def test_allowed_skill_executes(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        tool = SkillTool(adapter=adapter, skill_patterns=["zz-write-*"])

        result = tool.execute(skill="zz-write-report")

        assert result.success is True
        assert "# Write report body" in result.content

    def test_no_patterns_unrestricted(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        tool = SkillTool(adapter=adapter)

        result = tool.execute(skill="zz-code-review")

        assert result.success is True

    def test_turn_context_allowlist_overrides_instance(self, tmp_path):
        """执行器写入的 ContextVar 作用域优先（hex 共享注册表路径）。"""
        from backend.tools import skill_tool

        adapter = _make_adapter(tmp_path)
        tool = SkillTool(adapter=adapter)

        token = skill_tool.set_turn_skill_allowlist({"zz-write-report"})
        try:
            assert tool._resolve_allowed() == {"zz-write-report"}
            result = tool.execute(skill="zz-code-review")
            assert result.success is False
            assert "unknown skill" in (result.error or "")
        finally:
            skill_tool.reset_turn_skill_allowlist(token)

        # 作用域恢复后回到无限制
        assert tool._resolve_allowed() is None

    def test_inject_skill_scope_sets_patterns_on_registered_tools(self):
        registry = ToolRegistry()
        tool = SkillTool(adapter=object())
        registry.register(tool)

        count = inject_skill_scope(registry, ["zz-write-*"])

        assert count == 1
        assert tool.skill_patterns == ["zz-write-*"]


# =====================================================================
# 4. ChatService._skill_activation_block — allowed 透传
# =====================================================================


class _RecordingSkillPort:
    """记录 auto_activate 调用参数的假 skills port。"""

    def __init__(self) -> None:
        self.calls: list = []

    def list_skills(self):
        return []

    async def execute(self, name, action, args):  # pragma: no cover
        raise NotImplementedError

    def auto_activate(self, message, allowed=None):
        from types import SimpleNamespace

        self.calls.append((message, allowed))
        return SimpleNamespace(context_block="", names=())


def test_activation_block_forwards_allowed():
    port = _RecordingSkillPort()
    _skill_activation_block("hello", port, allowed={"zz-write-report"})
    assert port.calls == [("hello", {"zz-write-report"})]


def test_activation_block_unrestricted_by_default():
    port = _RecordingSkillPort()
    _skill_activation_block("hello", port)
    assert port.calls == [("hello", None)]


# =====================================================================
# 5. build_skills_block — allowed 过滤
# =====================================================================


def test_build_skills_block_filters_by_allowed(tmp_path, monkeypatch):
    """L5 技能清单注入只列允许集内的技能。"""
    from backend.adapters.out.skill import inproc

    adapter = _make_adapter(tmp_path)
    monkeypatch.setattr(inproc, "get_singleton", lambda: adapter)

    from backend.chat.env_context import build_skills_block

    block = build_skills_block(allowed={"zz-write-report"})

    assert "/zz-write-report" in block
    assert "/zz-code-review" not in block


# =====================================================================
# 6. ChatService._resolve_session_skill_allowlist — 会话绑定解析
# =====================================================================


class _PortWithNames:
    """只实现 list_skills 的最小 skills port。"""

    def __init__(self, names):
        self._names = list(names)

    def list_skills(self):
        from types import SimpleNamespace

        return [SimpleNamespace(name=n) for n in self._names]

    async def execute(self, name, action, args):  # pragma: no cover
        raise NotImplementedError

    def auto_activate(self, message, allowed=None):  # pragma: no cover
        raise NotImplementedError


def _make_chat_service(skills_port=None):
    from unittest.mock import MagicMock

    from backend.adapters.out.event.stdout_adapter import StdoutEventAdapter
    from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
    from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
    from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
    from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
    from backend.application.services.chat_service import ChatService

    return ChatService(
        llm=MockLLMAdapter(responses=[]),
        tools=InprocToolAdapter(registry=MagicMock(list=MagicMock(return_value=[]))),
        skills=skills_port or _PortWithNames([]),
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=StdoutEventAdapter(verbose=False),
    )


def _patch_binding(monkeypatch, agent_id, row):
    import backend.chat.specialist_binding as binding
    from backend.data import agent_repo

    class _Repo:
        def get(self, _agent_id):
            return row

    monkeypatch.setattr(agent_repo, "AgentRepository", _Repo)
    if isinstance(agent_id, Exception):
        def _raise(_session_id):
            raise agent_id

        monkeypatch.setattr(binding, "resolve_bound_specialist", _raise)
        monkeypatch.setattr(binding, "resolve_bound_specialist_strict", _raise)
    else:
        monkeypatch.setattr(binding, "resolve_bound_specialist", lambda _sid: agent_id)
        monkeypatch.setattr(
            binding, "resolve_bound_specialist_strict", lambda _sid: agent_id
        )


def test_session_allowlist_unbound_is_none(monkeypatch):
    service = _make_chat_service()
    _patch_binding(monkeypatch, "primary", None)
    assert service._resolve_session_skill_allowlist("s1") is None


def test_session_allowlist_resolves_wildcard(monkeypatch):
    """会话绑定写作专家 → 通配展开为具体技能名集合。"""
    service = _make_chat_service(_PortWithNames(["zz-write-report", "zz-code-review"]))
    _patch_binding(
        monkeypatch, "writer", {"id": "writer", "enabled": True, "skills": ["zz-write-*"]}
    )
    assert service._resolve_session_skill_allowlist("s1") == {"zz-write-report"}


def test_session_allowlist_empty_skills_is_none(monkeypatch):
    service = _make_chat_service(_PortWithNames(["zz-write-report"]))
    _patch_binding(monkeypatch, "writer", {"id": "writer", "enabled": True, "skills": []})
    assert service._resolve_session_skill_allowlist("s1") is None


def test_session_allowlist_fails_closed_on_error(monkeypatch):
    """专家归属无法解析 → 拒绝全部技能（fail-closed，安全审查 HIGH）。"""
    service = _make_chat_service()
    _patch_binding(monkeypatch, RuntimeError("db down"), None)
    assert service._resolve_session_skill_allowlist("s1") == set()


def test_session_allowlist_fails_closed_when_agent_row_unreadable(monkeypatch):
    """已判定为专家但档案读取失败 → 拒绝全部技能，而不是退化为不受限。"""
    import backend.chat.specialist_binding as binding
    from backend.data import agent_repo

    class _BoomRepo:
        def get(self, _agent_id):
            raise RuntimeError("db locked")

    monkeypatch.setattr(agent_repo, "AgentRepository", _BoomRepo)
    monkeypatch.setattr(
        binding, "resolve_bound_specialist_strict", lambda _sid: "writer"
    )
    service = _make_chat_service()
    assert service._resolve_session_skill_allowlist("s1") == set()


async def test_execute_tool_calls_scoped_sets_and_restores_allowlist(monkeypatch):
    """执行器把本轮允许集写入 ContextVar，结束后恢复（hex 路径堵漏）。"""
    from backend.tools import skill_tool

    service = _make_chat_service()
    captured = {}

    async def _fake_execute(session_id, tool_calls, run):
        captured["value"] = skill_tool._TURN_SKILL_ALLOWLIST.get()
        return False

    monkeypatch.setattr(service, "_execute_tool_calls", _fake_execute)

    result = await service._execute_tool_calls_scoped(
        "s1", [], None, {"zz-write-report"}
    )

    assert result is False
    assert captured["value"] == frozenset({"zz-write-report"})
    assert skill_tool._TURN_SKILL_ALLOWLIST.get() is skill_tool._UNSET


# =====================================================================
# 7. SageAgent 构造期接线 — profile.skills → SkillTool.skill_patterns
# =====================================================================


def test_sage_agent_injects_skill_scope_from_profile(monkeypatch):
    """SageAgent 构造时把 profile['skills'] 注入注册表内 SkillTool。"""
    from backend.agents import profiles

    profile = {
        "id": "writer",
        "role": "writer",
        "enabled": True,
        "skills": ["zz-write-*"],
    }
    monkeypatch.setattr(profiles, "get_enabled_agent", lambda _agent_id: profile)

    from backend.core.legacy.agent import SageAgent

    agent = SageAgent(agent_id="writer")
    skill_tool = agent.tool_registry.get("skill")

    assert skill_tool is not None
    assert skill_tool.skill_patterns == ["zz-write-*"]
