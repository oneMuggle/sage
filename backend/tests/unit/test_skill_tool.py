"""M2 part B — skill 工具单测。

覆盖:
- slash command 解析 + 执行 happy path（POST /skills/command 同一函数）
- 非 slash 技能回退 adapter.execute（POST /skills/{name}/execute 同一函数）
- 未知技能 → 错误 ToolResult 列出可用技能名
- args 词法切分 / 非法引号 / 空名
- 技能执行失败 → success=False 透传
- 默认惰性复用 REST 路由层单例（同注册表）
- 能力分级 EXECUTE + 注册表登记
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence

import pytest
from sage_core import SkillResult

from backend.skills.base import BaseSkill, SkillSchema
from backend.skills.registry import SkillRegistry
from backend.tools import ToolRegistry, register_all_tools
from backend.tools.permissions import ToolCapability, classify_tool
from backend.tools.skill_tool import SKILL_TOOL_NAME, SkillTool

pytestmark = pytest.mark.unit


class _StubSkillAdapter:
    """InprocSkillAdapter 存根：记录调用，可配置 LookupError 回退。"""

    def __init__(
        self,
        names: Sequence[str],
        slash_commands: Optional[Sequence[str]] = None,
        fail_command: Optional[str] = None,
    ) -> None:
        self._names = list(names)
        self._slash = set(slash_commands if slash_commands is not None else names)
        self._fail_command = fail_command
        self.command_calls: List[tuple] = []
        self.execute_calls: List[tuple] = []

    def has_skill(self, name: str) -> bool:
        return name in self._names

    def list_skills(self) -> List[SimpleNamespace]:
        return [SimpleNamespace(name=n) for n in self._names]

    async def execute_command(self, command: str, args: Sequence[str] = ()) -> SkillResult:
        if command not in self._slash:
            raise LookupError(f"slash command not registered: {command!r}")
        if command == self._fail_command:
            return SkillResult(success=False, error="脚本执行失败 (exit_code=1): boom")
        self.command_calls.append((command, list(args)))
        return SkillResult(success=True, content=f"cmd:{command}:{list(args)}")

    async def execute(self, name: str, action: str, args: Dict[str, Any]) -> SkillResult:
        self.execute_calls.append((name, action, dict(args)))
        return SkillResult(success=True, content=f"exec:{name}:{args}")


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_skill_tool_executes_slash_command_via_existing_path():
    """已注册 slash 技能 → 走 execute_command（POST /skills/command 同一函数）。"""
    # Arrange
    adapter = _StubSkillAdapter(names=["review", "search"], slash_commands=["review"])
    tool = SkillTool(adapter=adapter)

    # Act
    result = tool.execute(skill="review", args="--fast src/")

    # Assert
    assert result.success is True
    assert result.content == "cmd:review:['--fast', 'src/']"
    assert adapter.command_calls == [("review", ["--fast", "src/"])]
    assert adapter.execute_calls == []


def test_skill_tool_falls_back_to_execute_for_non_slash_skill():
    """非 slash 技能（builtin 等）→ LookupError 回退 adapter.execute。"""
    # Arrange
    adapter = _StubSkillAdapter(names=["writer"], slash_commands=[])
    tool = SkillTool(adapter=adapter)

    # Act
    result = tool.execute(skill="writer", args="写首诗")

    # Assert
    assert result.success is True
    assert result.content == "exec:writer:{'args': '写首诗'}"
    assert adapter.execute_calls == [("writer", "", {"args": "写首诗"})]
    assert adapter.command_calls == []


def test_skill_tool_without_args_passes_empty_list():
    """无 args → 空参数列表。"""
    # Arrange
    adapter = _StubSkillAdapter(names=["review"])
    tool = SkillTool(adapter=adapter)

    # Act
    result = tool.execute(skill="review")

    # Assert
    assert result.success is True
    assert adapter.command_calls == [("review", [])]


# ---------------------------------------------------------------------------
# 错误路径
# ---------------------------------------------------------------------------


def test_unknown_skill_error_lists_available_names():
    """未知技能 → success=False + 可用技能清单。"""
    # Arrange
    adapter = _StubSkillAdapter(names=["review", "search"])
    tool = SkillTool(adapter=adapter)

    # Act
    result = tool.execute(skill="nope")

    # Assert
    assert result.success is False
    assert "unknown skill: 'nope'" in (result.error or "")
    assert "review" in (result.error or "")
    assert "search" in (result.error or "")


def test_empty_skill_name_is_rejected():
    """空技能名 → 错误 ToolResult。"""
    # Arrange
    tool = SkillTool(adapter=_StubSkillAdapter(names=["review"]))

    # Act / Assert
    assert tool.execute(skill="").success is False
    assert tool.execute(skill="   ").success is False


def test_unbalanced_quotes_in_args_is_rejected():
    """args 引号不配对 → 错误而非抛异常。"""
    # Arrange
    tool = SkillTool(adapter=_StubSkillAdapter(names=["review"]))

    # Act
    result = tool.execute(skill="review", args='--msg "unclosed')

    # Assert
    assert result.success is False
    assert "args 解析失败" in (result.error or "")


def test_skill_execution_failure_propagates_error():
    """技能内部失败（脚本退出码非 0 等）→ success=False 透传 error。"""
    # Arrange
    adapter = _StubSkillAdapter(names=["deploy"], fail_command="deploy")
    tool = SkillTool(adapter=adapter)

    # Act
    result = tool.execute(skill="deploy")

    # Assert
    assert result.success is False
    assert "脚本执行失败" in (result.error or "")


def test_skill_name_is_stripped_before_lookup():
    """技能名首尾空白被剥离。"""
    # Arrange
    adapter = _StubSkillAdapter(names=["review"])
    tool = SkillTool(adapter=adapter)

    # Act
    result = tool.execute(skill="  review  ")

    # Assert
    assert result.success is True
    assert adapter.command_calls == [("review", [])]


# ---------------------------------------------------------------------------
# REST 同源单例 + 能力分级
# ---------------------------------------------------------------------------


def test_default_adapter_reuses_inproc_singleton(monkeypatch):
    """adapter=None → 惰性复用 inproc 模块级单例（与 REST 路由共享注册表）。

    M2b 重构：单例缓存搬到 ``backend.adapters.out.skill.inproc``，路由层
    与工具层都委托到 ``inproc.get_singleton()``。monkeypatch setattr 目标
    改为 inproc 模块，验证 SkillTool 在不注入 adapter 时复用同一实例。
    """
    # Arrange
    import backend.adapters.out.skill.inproc as inproc_module

    stub = _StubSkillAdapter(names=["review"])
    monkeypatch.setattr(inproc_module, "_skill_adapter_singleton", stub)
    tool = SkillTool()  # 不注入 adapter

    # Act
    result = tool.execute(skill="review")

    # Assert — 命中的是 inproc 层单例（路由层 thin wrapper 也委托此处）
    assert result.success is True
    assert tool._resolve_adapter() is stub


def test_skill_tool_registered_and_classified_execute():
    """skill 工具在注册表中, 能力分级为 EXECUTE（M1 审批闸口拦截）。"""
    # Arrange
    registry = ToolRegistry()
    register_all_tools(registry)

    # Act / Assert
    assert registry.exists(SKILL_TOOL_NAME)
    assert classify_tool(SKILL_TOOL_NAME) is ToolCapability.EXECUTE


def test_schema_declares_skill_param_required():
    """LLM schema: skill 必填, args 可选。"""
    # Arrange
    tool = SkillTool(adapter=_StubSkillAdapter(names=[]))

    # Act
    schema = tool.schema

    # Assert
    assert schema.name == "skill"
    assert schema.parameters["required"] == ["skill"]
    assert "skill" in schema.parameters["properties"]
    assert "args" in schema.parameters["properties"]


# ---------------------------------------------------------------------------
# SkillPort 接线（关闭 main.py skills=None TODO）
# ---------------------------------------------------------------------------


class _EchoSkill(BaseSkill):
    """测试用技能：回显参数。"""

    def _build_schema(self) -> SkillSchema:
        return SkillSchema(name="echo", description="回显", triggers=["echo"])

    def execute(self, params, context):
        from backend.skills.base import SkillResult as BaseSkillResult

        return BaseSkillResult(content=f"echo:{sorted(params.items())}")

    def match(self, text: str) -> bool:
        return "echo" in text.lower()


def test_build_chat_service_provides_non_none_skill_port():
    """_build_chat_service 装配的 ChatService.skills 非 None 且可用。"""
    # Arrange / Act
    from backend.main import _build_chat_service

    service = _build_chat_service()

    # Assert — SkillPort 协议两方法可用
    assert service.skills is not None
    names = [spec.name for spec in service.skills.list_skills()]
    assert "search" in names  # builtin 已装载


async def test_skill_invocation_through_chat_service_port_with_stub_skill():
    """通过 ChatService.skills 端口执行存根技能（单元）。"""
    # Arrange
    from unittest.mock import MagicMock

    from backend.adapters.out.event.stdout_adapter import StdoutEventAdapter
    from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
    from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
    from backend.adapters.out.skill import InprocSkillAdapter
    from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
    from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
    from backend.application.services.chat_service import ChatService

    registry = SkillRegistry()
    registry.register(_EchoSkill())
    adapter = InprocSkillAdapter(registry=registry)
    service = ChatService(
        llm=MockLLMAdapter(responses=[]),
        tools=InprocToolAdapter(registry=MagicMock(list=MagicMock(return_value=[]))),
        skills=adapter,
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=StdoutEventAdapter(verbose=False),
    )

    # Act
    result = await service.skills.execute("echo", "", {"msg": "hi"})

    # Assert
    assert result.success is True
    assert "echo:" in result.content


async def test_chat_service_skill_port_unknown_skill_returns_failure():
    """端口契约: 未知技能 success=False + error（不抛异常）。"""
    # Arrange
    from backend.adapters.out.skill import InprocSkillAdapter

    adapter = InprocSkillAdapter(registry=SkillRegistry())

    # Act
    result = await adapter.execute("ghost", "", {})

    # Assert
    assert result.success is False
    assert "not found" in (result.error or "")
