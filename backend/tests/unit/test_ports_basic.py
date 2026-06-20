"""验证 ports/ Protocol 可作为类型提示。

仅覆盖：
1. 所有 6 个 port 可通过 ``backend.ports`` 顶层导入
2. 关键 Protocol 方法可被 ``hasattr`` 识别（不依赖运行时实现）
3. 最小 mock 类可以满足 Protocol 的结构性子类型检查
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from sage_core import Message, Role, SkillResult, SkillSpec, ToolResult, ToolSpec
from sage_core.repositories import EventPort, LLMPort, MetricPort, SkillPort, StoragePort, ToolPort

pytestmark = pytest.mark.unit


# ---------- 导入与可发现性 ----------


def test_all_ports_importable() -> None:
    """6 个 Protocol 都能从 backend.ports 顶层导入。"""
    assert LLMPort is not None
    assert ToolPort is not None
    assert SkillPort is not None
    assert StoragePort is not None
    assert MetricPort is not None
    assert EventPort is not None


def test_all_ports_re_exported_in_init() -> None:
    """``backend.ports.__all__`` 必须包含全部 6 个 port。"""
    from backend.ports import __all__ as ports_all

    assert set(ports_all) == {
        "LLMPort",
        "ToolPort",
        "SkillPort",
        "StoragePort",
        "MetricPort",
        "EventPort",
    }


# ---------- 方法存在性 ----------


def test_metric_port_protocol_methods() -> None:
    """MetricPort 暴露 counter / histogram / gauge。"""
    assert hasattr(MetricPort, "counter")
    assert hasattr(MetricPort, "histogram")
    assert hasattr(MetricPort, "gauge")


def test_event_port_protocol_methods() -> None:
    """EventPort 暴露 emit。"""
    assert hasattr(EventPort, "emit")


def test_llm_port_protocol_methods() -> None:
    """LLMPort 暴露 chat 与 chat_stream。"""
    assert hasattr(LLMPort, "chat")
    assert hasattr(LLMPort, "chat_stream")


def test_tool_port_protocol_methods() -> None:
    """ToolPort 暴露 list_tools / execute。"""
    assert hasattr(ToolPort, "list_tools")
    assert hasattr(ToolPort, "execute")


def test_skill_port_protocol_methods() -> None:
    """SkillPort 暴露 list_skills / execute。"""
    assert hasattr(SkillPort, "list_skills")
    assert hasattr(SkillPort, "execute")


def test_storage_port_protocol_methods() -> None:
    """StoragePort 暴露 5 个会话/消息 CRUD 方法。"""
    for name in (
        "append_message",
        "get_messages",
        "create_session",
        "list_sessions",
        "delete_session",
    ):
        assert hasattr(StoragePort, name), f"StoragePort 缺少方法: {name}"


# ---------- 最小 mock 可满足 Protocol ----------


class _InMemoryMetric:
    """最小 MetricPort 实现。"""

    def __init__(self) -> None:
        self.counters: list[tuple[str, dict[str, str]]] = []
        self.histograms: list[tuple[str, float, dict[str, str]]] = []
        self.gauges: list[tuple[str, float, dict[str, str]]] = []

    def counter(self, name: str, labels: dict[str, str]) -> None:
        self.counters.append((name, labels))

    def histogram(self, name: str, value: float, labels: dict[str, str]) -> None:
        self.histograms.append((name, value, labels))

    def gauge(self, name: str, value: float, labels: dict[str, str]) -> None:
        self.gauges.append((name, value, labels))


class _InMemoryEvent:
    """最小 EventPort 实现。"""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


class _InMemoryStorage:
    """最小 StoragePort 实现。"""

    def __init__(self) -> None:
        self.messages: list[tuple[str, Message]] = []
        self.sessions: dict[str, str] = {}

    async def append_message(self, session_id: str, message: Message) -> None:
        self.messages.append((session_id, message))

    async def get_messages(self, session_id: str, limit: int = 50) -> list[Message]:
        return [m for sid, m in self.messages if sid == session_id][:limit]

    async def create_session(self, title: str = "") -> str:
        new_id = f"ses_{len(self.sessions) + 1}"
        self.sessions[new_id] = title
        return new_id

    async def list_sessions(self) -> list[dict[str, Any]]:
        return [{"id": k, "title": v} for k, v in self.sessions.items()]

    async def delete_session(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)
        self.messages = [(s, m) for s, m in self.messages if s != session_id]


class _InMemoryTool:
    """最小 ToolPort 实现。"""

    def list_tools(self) -> list[ToolSpec]:
        return [ToolSpec(name="echo", description="回显输入")]

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output=str(args))


class _InMemorySkill:
    """最小 SkillPort 实现。"""

    def list_skills(self) -> list[SkillSpec]:
        return [SkillSpec(name="greet", description="打招呼")]

    async def execute(
        self,
        name: str,
        action: str,
        args: dict[str, Any],
    ) -> SkillResult:
        return SkillResult(success=True, content=f"{name}:{action}")


class _InMemoryLLM:
    """最小 LLMPort 实现。"""

    async def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> Message:
        return Message(role=Role.ASSISTANT, content="ok")

    def chat_stream(
        self,
        messages: list[Message],
    ) -> AsyncIterator[str]:
        async def _gen() -> AsyncIterator[str]:
            yield "ok"

        return _gen()


def test_metric_port_structural_typing() -> None:
    """任意实现 ``counter/histogram/gauge`` 的类都满足 MetricPort。"""
    impl = _InMemoryMetric()
    metric: MetricPort = impl
    metric.counter("c", {"k": "v"})
    metric.histogram("h", 0.1, {})
    metric.gauge("g", 1.0, {})
    assert len(impl.counters) == 1
    assert impl.histograms[0][0] == "h"
    assert impl.gauges[0][0] == "g"


def test_event_port_structural_typing() -> None:
    """任意实现 ``emit`` 的类都满足 EventPort。"""
    evt: EventPort = _InMemoryEvent()
    evt.emit("x", {"y": 1})
    assert _InMemoryEvent().events == []  # 新实例仍是空


def test_storage_port_structural_typing() -> None:
    """任意实现 5 个 CRUD 方法的类都满足 StoragePort。"""
    storage: StoragePort = _InMemoryStorage()
    assert hasattr(storage, "append_message")
    assert hasattr(storage, "get_messages")
    assert hasattr(storage, "create_session")
    assert hasattr(storage, "list_sessions")
    assert hasattr(storage, "delete_session")


def test_tool_port_structural_typing() -> None:
    """任意实现 ``list_tools/execute`` 的类都满足 ToolPort。"""
    tool: ToolPort = _InMemoryTool()
    specs = tool.list_tools()
    assert specs[0].name == "echo"


def test_skill_port_structural_typing() -> None:
    """任意实现 ``list_skills/execute`` 的类都满足 SkillPort。"""
    skill: SkillPort = _InMemorySkill()
    specs = skill.list_skills()
    assert specs[0].name == "greet"


def test_llm_port_structural_typing() -> None:
    """任意实现 ``chat/chat_stream`` 的类都满足 LLMPort。"""
    llm: LLMPort = _InMemoryLLM()
    assert hasattr(llm, "chat")
    assert hasattr(llm, "chat_stream")


# ---------- ports 零外部依赖契约 ----------


def test_ports_only_depend_on_domain() -> None:
    """ports/ 仅允许 import ``backend.domain.*``，禁止外部依赖。"""
    import pathlib
    import re

    ports_dir = pathlib.Path(__file__).resolve().parents[2] / "ports"
    assert ports_dir.is_dir(), f"ports/ 不存在: {ports_dir}"

    allowed_stdlib = {
        "dataclasses",
        "enum",
        "typing",
        "abc",
        "collections",
        "__future__",
        "collections.abc",
    }
    allowed_internal = ("backend.domain", "backend.ports")

    import_re = re.compile(r"^\s*(?:from|import)\s+([\w\.]+)")
    offenders: list[str] = []

    for py_file in sorted(ports_dir.rglob("*.py")):
        for line in py_file.read_text(encoding="utf-8").splitlines():
            match = import_re.match(line)
            if not match:
                continue
            mod = match.group(1)
            if mod.startswith(allowed_internal):
                continue
            root = mod.split(".")[0]
            if root in allowed_stdlib:
                continue
            offenders.append(f"{py_file.name}: {line.strip()}")

    assert offenders == [], "ports/ 出现非法外部 import:\n" + "\n".join(offenders)
