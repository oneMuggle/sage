# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""B2 声明式并行调度测试（DSH 对标 R3）。

覆盖：_plan_execution_groups 分组语义（全池 / write 屏障切分 /
concurrency_safe 显式压制与升级 / 钩子全串行 / 预算降级 / 池上限）与
run_loop 混合调度的事件顺序保持（write → read 不被重排）。

注意： MagicMock 的未声明属性会自动生成 truthy 子 mock —— 构造工具替身
时必须**显式**传 ``concurrency_safe=None``，才能走到 risk==READ 回落
判定（生产代码的 getattr 缺省语义）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.domain.risk import RiskClass

pytestmark = pytest.mark.unit


def _tc(idx, name, args_json='{"x": 1}'):
    call = MagicMock()
    call.id = f"call_{idx}"
    call.name = name
    call.arguments = args_json
    return call


def _tool(risk=RiskClass.READ, safe=None, blocking=False):
    return MagicMock(risk=risk, is_blocking=blocking, concurrency_safe=safe)


READ_TOOL = _tool()  # None → 回落 READ 判定
WRITE_TOOL = _tool(risk=RiskClass.WRITE_LOCAL)
SAFE_READ = _tool(safe=True)
SAFE_WRITE = _tool(risk=RiskClass.WRITE_LOCAL, safe=True)
BLOCKED_READ = _tool(safe=False)


def _agent_with(tools):
    """tools: {name: tool}；registry.get 按名分发。"""
    agent = SageAgent()
    agent.tool_registry.get = MagicMock(side_effect=lambda name: tools.get(name))
    return agent


def _free_enforcer():
    enforcer = MagicMock()
    enforcer.check.return_value = MagicMock(allowed=True, needs_approval=False)
    return enforcer


class TestPlanExecutionGroups:
    def test_all_read_single_pool(self):
        agent = _agent_with({"read_file": READ_TOOL})
        batch = [_tc(1, "read_file"), _tc(2, "read_file"), _tc(3, "read_file")]
        groups = agent._plan_execution_groups(batch, _free_enforcer(), [], 0)
        assert groups == [("pool", batch)]

    def test_write_splits_into_barriers(self):
        """[read, write, read] → 池 / 串行屏障 / 池，顺序保持。"""
        agent = _agent_with({"read_file": READ_TOOL, "edit_file": WRITE_TOOL})
        r1, w, r2 = _tc(1, "read_file"), _tc(2, "edit_file"), _tc(3, "read_file")
        groups = agent._plan_execution_groups([r1, w, r2], _free_enforcer(), [], 0)
        assert groups == [("pool", [r1]), ("serial", [w]), ("pool", [r2])]

    def test_explicit_concurrency_safe_false_suppresses_read(self):
        agent = _agent_with({"special_read": BLOCKED_READ, "read_file": READ_TOOL})
        a, b = _tc(1, "special_read"), _tc(2, "read_file")
        groups = agent._plan_execution_groups([a, b], _free_enforcer(), [], 0)
        assert groups == [("serial", [a]), ("pool", [b])]

    def test_explicit_concurrency_safe_true_upgrades_write(self):
        agent = _agent_with({"upsert": SAFE_WRITE})
        batch = [_tc(1, "upsert"), _tc(2, "upsert")]
        groups = agent._plan_execution_groups(batch, _free_enforcer(), [], 0)
        assert groups == [("pool", batch)]

    def test_hooks_force_all_serial(self):
        agent = _agent_with({"read_file": READ_TOOL})
        batch = [_tc(1, "read_file"), _tc(2, "read_file")]
        groups = agent._plan_execution_groups(
            batch, _free_enforcer(), [MagicMock()], 0
        )
        assert groups == [("serial", [batch[0]]), ("serial", [batch[1]])]

    def test_approval_needed_call_is_barrier(self):
        agent = _agent_with({"read_file": READ_TOOL, "bash": WRITE_TOOL})
        enforcer = MagicMock()
        # bash 需审批，其余放行
        enforcer.check.side_effect = lambda name, args: MagicMock(
            allowed=True, needs_approval=(name == "bash")
        )
        r1, b, r2 = _tc(1, "read_file"), _tc(2, "bash"), _tc(3, "read_file")
        groups = agent._plan_execution_groups([r1, b, r2], enforcer, [], 0)
        assert groups == [("pool", [r1]), ("serial", [b]), ("pool", [r2])]

    def test_budget_exhaustion_degrades_rest_to_serial(self):
        agent = _agent_with({"read_file": READ_TOOL})
        agent._effective_max_tool_calls_per_run = MagicMock(return_value=3)
        batch = [_tc(i, "read_file") for i in range(1, 5)]
        # used=1 → 余量 2：前两个入池，预算尽后其余 serial
        groups = agent._plan_execution_groups(batch, _free_enforcer(), [], 1)
        assert groups == [
            ("pool", [batch[0], batch[1]]),
            ("serial", [batch[2]]),
            ("serial", [batch[3]]),
        ]

    def test_pool_cap_starts_new_group(self):
        agent = _agent_with({"read_file": READ_TOOL})
        agent._effective_max_tool_calls_per_run = MagicMock(return_value=100)
        batch = [_tc(i, "read_file") for i in range(1, 11)]  # 10 个 > 上限 8
        groups = agent._plan_execution_groups(batch, _free_enforcer(), [], 0)
        pools = [g for kind, g in groups if kind == "pool"]
        assert [len(p) for p in pools] == [8, 2]

    def test_single_call_is_serial(self):
        agent = _agent_with({"read_file": READ_TOOL})
        batch = [_tc(1, "read_file")]
        assert agent._plan_execution_groups(batch, _free_enforcer(), [], 0) == [
            ("serial", batch)
        ]

    def test_whitelist_violation_all_serial(self):
        agent = _agent_with({"read_file": READ_TOOL, "grep": READ_TOOL})
        agent.profile = {"tools": ["read_file"]}
        batch = [_tc(1, "read_file"), _tc(2, "grep")]
        groups = agent._plan_execution_groups(batch, _free_enforcer(), [], 0)
        assert groups == [("serial", [batch[0]]), ("serial", [batch[1]])]

    def test_is_parallel_eligible_unchanged_semantics(self):
        """L6 整批判定与分组规划同源：全 READ 批两方法结论一致。"""
        agent = _agent_with({"read_file": READ_TOOL})
        batch = [_tc(1, "read_file"), _tc(2, "read_file")]
        assert agent._is_parallel_eligible(batch, _free_enforcer(), [], 0) is True
        groups = agent._plan_execution_groups(batch, _free_enforcer(), [], 0)
        assert groups == [("pool", batch)]


class TestMixedSchedulingOrder:
    @pytest.mark.asyncio()
    async def test_write_read_write_order_preserved(self):
        """混合批次：事件与 tool 消息严格按模型顺序产出（屏障语义）。"""
        agent = SageAgent()
        agent.llm_client = MagicMock()

        executed = []

        def _tool_call_response():
            resp = MagicMock()
            resp.content = None
            resp.finish_reason = "tool_calls"
            resp.tool_calls = [
                _tc(1, "read_file"),
                _tc(2, "edit_file"),
                _tc(3, "read_file"),
            ]
            return resp

        def _text_response(text):
            resp = MagicMock()
            resp.content = text
            resp.finish_reason = "stop"
            resp.tool_calls = []
            return resp

        agent.llm_client.chat = AsyncMock(
            side_effect=[_tool_call_response(), _text_response("done")]
        )

        def _make_tool(name):
            tool = _tool(
                risk=RiskClass.READ if name == "read_file" else RiskClass.WRITE_LOCAL
            )
            tool.execute.side_effect = (
                lambda **kw: executed.append(name)
                or MagicMock(success=True, content=name, error=None)
            )
            return tool

        agent.tool_registry.get = MagicMock(
            side_effect=lambda name: {
                "read_file": _make_tool("read_file"),
                "edit_file": _make_tool("edit_file"),
            }[name]
        )
        agent.permission_enforcer = _free_enforcer()

        messages = [{"role": "user", "content": "hi"}]
        async for _ in agent.run_loop(messages, max_iterations=5):
            pass

        # 执行顺序：read → edit → read（屏障语义，不被并发重排）
        assert executed == ["read_file", "edit_file", "read_file"]
        # tool 结果消息顺序与模型顺序一致
        tool_msgs = [
            m for m in messages if isinstance(m, dict) and m.get("role") == "tool"
        ]
        assert [m["tool_call_id"] for m in tool_msgs][:3] == [
            "call_1",
            "call_2",
            "call_3",
        ]
