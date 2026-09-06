# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""L6 并行只读工具批次 + L12-lite 中断取消当前工具 (批次 C-3) 单元测试。"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.domain.risk import RiskClass

pytestmark = pytest.mark.unit


class _FakeTool:
    """可记录调用的假工具。"""

    def __init__(self, name: str, risk: RiskClass = RiskClass.READ, delay: float = 0.0,
                 is_blocking: bool = False, content: str = "ok"):
        self.name = name
        self.risk = risk
        self.is_blocking = is_blocking
        self.delay = delay
        self.content = content
        self.calls = 0

    def execute(self, **kwargs):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return MagicMock(success=True, content=self.content, error=None)


def _make_registry(tools):
    registry = MagicMock()
    def get(name):
        return tools.get(name)
    registry.get = get
    return registry


def _make_agent(tools, responses):
    agent = SageAgent()
    agent.tool_registry = _make_registry(tools)
    client = MagicMock()
    client.chat = AsyncMock(side_effect=list(responses))
    agent.llm_client = client
    return agent


def _tool_calls(*pairs):
    return [
        LLMToolCall(id=f"c{i}", name=name, arguments=arguments or "{}")
        for i, (name, arguments) in enumerate(pairs)
    ]


# ---- L6 并行批次 ----


@pytest.mark.asyncio()
async def test_parallel_readonly_batch_executes_and_orders():
    """两个 READ 工具 → 并行执行, ACTING 先于 OBSERVING, 消息按原顺序。"""
    slow = _FakeTool("search_web", delay=0.15, content="web-result")
    fast = _FakeTool("read_file", content="file-result")
    tools = {"search_web": slow, "read_file": fast}
    round1 = LLMResponse(content="", tool_calls=_tool_calls(
        ("search_web", '{"query": "x"}'),
        ("read_file", '{"path": "a.py"}'),
    ))
    final = LLMResponse(content="done")
    agent = _make_agent(tools, [round1, final])

    events = []
    messages = [{"role": "user", "content": "x"}]
    async for evt in agent.run_loop(messages):
        events.append(evt)

    assert slow.calls == 1
    assert fast.calls == 1
    states = [e.state.value for e in events]
    # 两个 ACTING 都在任一 OBSERVING 之前 (并行先发全部 ACTING)
    acting_idx = [i for i, s in enumerate(states) if s == "acting"]
    observing_idx = [i for i, s in enumerate(states) if s == "observing"]
    assert len(acting_idx) == 2
    assert len(observing_idx) == 2
    assert max(acting_idx) < min(observing_idx)
    # OBSERVING 按原顺序: search_web 先
    assert "web-result" in events[observing_idx[0]].tool_result.content
    assert "file-result" in events[observing_idx[1]].tool_result.content
    # tool 消息按原顺序追加
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert [m["content"] for m in tool_msgs] == ['"web-result"', '"file-result"']
    assert events[-1].state.value == "done"


@pytest.mark.asyncio()
async def test_mixed_risk_batch_falls_back_to_serial():
    """批次含 WRITE 工具 → 不并行, 走串行路径 (行为不变)。"""
    write_tool = _FakeTool("write_file", risk=RiskClass.WRITE_LOCAL)
    read_tool = _FakeTool("read_file")
    tools = {"write_file": write_tool, "read_file": read_tool}
    round1 = LLMResponse(content="", tool_calls=_tool_calls(
        ("write_file", '{"path": "a"}'),
        ("read_file", '{"path": "a"}'),
    ))
    final = LLMResponse(content="done")
    agent = _make_agent(tools, [round1, final])

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    assert write_tool.calls == 1
    assert read_tool.calls == 1
    assert events[-1].state.value == "done"
    # 串行: 第一个 ACTING 与第一个 OBSERVING 交替出现
    states = [e.state.value for e in events]
    first_observing = states.index("observing")
    assert states.index("acting", 0, first_observing) < first_observing


@pytest.mark.asyncio()
async def test_hooks_present_disables_parallel():
    """配置了 pre_tool_use 钩子 → 回退串行 (钩子 deny/modify 是顺序语义)。"""
    read_tool = _FakeTool("read_file")
    tools = {"read_file": read_tool}

    class _FakeRepo:
        def get_json(self, key):
            return [{"event": "pre_tool_use", "matcher": "*", "command": "echo hi"}]

    from backend.hooks.config import load_hooks

    hooks = load_hooks(_FakeRepo())
    assert hooks  # 钩子配置有效

    agent = _make_agent(tools, [
        LLMResponse(content="", tool_calls=_tool_calls(
            ("read_file", "{}"), ("read_file", "{}"),
        )),
        LLMResponse(content="done"),
    ])
    # 强制注入已加载的钩子, 绕过真实 shell 执行
    agent._load_m6_hooks = lambda: hooks
    # 钩子命令 echo hi 会执行 — run_hook 用 create_subprocess_shell, 放行即可

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    assert read_tool.calls == 2
    assert events[-1].state.value == "done"
    # 串行语义: acting/observing 交替
    states = [e.state.value for e in events]
    first_obs = states.index("observing")
    assert states.index("acting", 0, first_obs) < first_obs


@pytest.mark.asyncio()
async def test_parallel_budget_overflow_falls_back():
    """批次超出预算余量 → 回退串行守卫(在精确超限点终止)。"""
    t1 = _FakeTool("read_file")
    t2 = _FakeTool("calculator")
    tools = {"read_file": t1, "calculator": t2}

    import os
    os.environ["SAGE_MAX_TOOL_CALLS_PER_RUN"] = "2"
    try:
        agent = _make_agent(tools, [
            LLMResponse(content="", tool_calls=_tool_calls(
                ("read_file", "{}"), ("read_file", "{}"),
            )),
            LLMResponse(content="", tool_calls=_tool_calls(
                ("read_file", "{}"), ("calculator", "{}"),
            )),
            LLMResponse(content="never"),
        ])
        events = []
        async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
            events.append(evt)
        assert events[-1].state.value == "failed"
        assert events[-1].error == "tool_budget_exceeded"
    finally:
        os.environ.pop("SAGE_MAX_TOOL_CALLS_PER_RUN", None)


# ---- L12-lite 中断即时取消 ----


@pytest.mark.asyncio()
async def test_interrupt_cancels_running_blocking_tool():
    """阻塞工具执行中收到 interrupt → 立即取消并 FAILED, 不等执行完成。"""
    slow = _FakeTool("bash", risk=RiskClass.EXEC, is_blocking=True, delay=30.0)
    tools = {"bash": slow}
    round1 = LLMResponse(content="", tool_calls=_tool_calls(("bash", '{"command": "sleep 30"}')))
    agent = _make_agent(tools, [round1])

    # EXEC 工具需审批; 注入全放行 enforcer 让工具真正进入执行段
    from backend.tools.permissions import PermissionDecision

    class _AllowEnforcer:
        def check(self, name, args):
            return PermissionDecision(allowed=True, needs_approval=False, reason="test")

    agent.permission_enforcer = _AllowEnforcer()

    started = time.monotonic()

    async def consume():
        events = []
        async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
            events.append(evt)
        return events

    consumer = asyncio.ensure_future(consume())
    await asyncio.sleep(0.3)  # 让工具进入执行
    agent.interrupt()
    events = await asyncio.wait_for(consumer, timeout=10)

    elapsed = time.monotonic() - started
    assert elapsed < 10  # 没有等 30s
    states = [e.state.value for e in events]
    assert states[-1] == "failed"
    assert events[-1].error == "interrupted by user"
    # 取消的 OBSERVING 事件带取消标注
    observing = [e for e in events if e.state.value == "observing"]
    assert any("被用户取消" in e.tool_result.content for e in observing)


@pytest.mark.asyncio()
async def test_no_interrupt_completes_normally():
    """不中断时竞争 helper 不改变语义。"""
    tool = _FakeTool("read_file", content="fine")
    tools = {"read_file": tool}
    agent = _make_agent(tools, [
        LLMResponse(content="", tool_calls=_tool_calls(("read_file", "{}"))),
        LLMResponse(content="done"),
    ])
    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)
    assert events[-1].state.value == "done"
    assert tool.calls == 1
