import asyncio
import types

from backend.core.legacy.agent_state import (
    AgentEvent,
    AgentState,
    ToolCallRequest,
    ToolCallResult,
)
from backend.orchestration import plan_preflight
from backend.orchestration.complexity_classifier import ComplexityClassification


class _Settings:
    plan_preflight_enabled = True
    plan_scout_enabled = True
    max_scout_iterations = 3


def _collect():
    events = []

    async def emit(event):
        events.append(event)

    return events, emit


def _patch_common(monkeypatch):
    """屏蔽外部依赖，只保留被测的接线逻辑。

    ``plan_preflight`` 在函数体内惰性 import ``build_llm_client_from_settings``
    与 ``build_utility_llm_client``，所以必须 patch ``llm_factory`` 模块属性
    而非 ``plan_preflight`` 上的名字；``classify_complexity`` 同理。
    两个工厂均返回同一 fake（``_clarify``/``_scout`` 由测试另行 monkeypatch），
    使 ``build_utility_llm_client(...) or client`` 的兜底解析到同一对象。
    """
    import backend.orchestration.complexity_classifier as classifier_module
    import backend.orchestration.llm_factory as llm_factory_module

    monkeypatch.setattr(
        plan_preflight, "preflight_master_enabled", lambda: True, raising=False
    )
    monkeypatch.setattr(
        plan_preflight, "load_orch_settings", lambda: _Settings(), raising=False
    )
    monkeypatch.setattr(
        llm_factory_module, "build_llm_client_from_settings", lambda: object()
    )
    monkeypatch.setattr(
        llm_factory_module, "build_utility_llm_client", lambda task_type=None: object()
    )
    return classifier_module


def test_simple_task_skips_scout_and_emits_stages(monkeypatch):
    classifier_module = _patch_common(monkeypatch)

    async def fake_classify(message, context=None):
        return ComplexityClassification(
            complexity="simple", research_needed=False, reasoning=""
        )

    async def fake_clarify(client, message, emit):
        return []

    monkeypatch.setattr(classifier_module, "classify_complexity", fake_classify)
    monkeypatch.setattr(plan_preflight, "_clarify", fake_clarify)

    events, emit = _collect()
    asyncio.run(plan_preflight.run_plan_preflight("改个颜色", emit=emit))

    stages = [
        e["plan_progress"]["stage"] for e in events if e["state"] == "plan_progress"
    ]
    assert "complexity_classify" in stages
    assert "clarify" in stages
    scout_event = next(
        e
        for e in events
        if e["state"] == "plan_progress"
        and e["plan_progress"]["stage"] == "scout"
    )
    assert scout_event["plan_progress"]["status"] == "skipped"


def test_medium_task_wraps_scout(monkeypatch):
    classifier_module = _patch_common(monkeypatch)

    async def fake_classify(message, context=None):
        return ComplexityClassification(
            complexity="medium", research_needed=True, reasoning=""
        )

    async def fake_clarify(client, message, emit):
        return []

    async def fake_scout(
        client, message, emit, clarifications, max_iterations=3, fallback_client=None
    ):
        return "- fact"

    monkeypatch.setattr(classifier_module, "classify_complexity", fake_classify)
    monkeypatch.setattr(plan_preflight, "_clarify", fake_clarify)
    monkeypatch.setattr(plan_preflight, "_scout", fake_scout)

    events, emit = _collect()
    result = asyncio.run(plan_preflight.run_plan_preflight("重构模块", emit=emit))

    assert result is not None
    scout_done = [
        e
        for e in events
        if e["state"] == "plan_progress"
        and e["plan_progress"]["stage"] == "scout"
        and e["plan_progress"]["status"] == "done"
    ]
    assert scout_done, events


def test_medium_scout_done_event_carries_fact_detail(monkeypatch):
    """lite scout 完成的 done 事件带 detail.facts —— 前端据此渲染事实区块。"""
    classifier_module = _patch_common(monkeypatch)

    async def fake_classify(message, context=None):
        return ComplexityClassification(
            complexity="medium", research_needed=True, reasoning=""
        )

    async def fake_clarify(client, message, emit):
        return []

    async def fake_scout(
        client, message, emit, clarifications, max_iterations=3, fallback_client=None
    ):
        return "- 事实甲在这里（来源：文档 A）\n- 事实乙在这里"

    monkeypatch.setattr(classifier_module, "classify_complexity", fake_classify)
    monkeypatch.setattr(plan_preflight, "_clarify", fake_clarify)
    monkeypatch.setattr(plan_preflight, "_scout", fake_scout)

    events, emit = _collect()
    asyncio.run(plan_preflight.run_plan_preflight("重构模块", emit=emit))

    scout_done = [
        e["plan_progress"]
        for e in events
        if e["state"] == "plan_progress"
        and e["plan_progress"]["stage"] == "scout"
        and e["plan_progress"]["status"] == "done"
    ]
    assert scout_done, events
    detail = scout_done[0].get("detail") or {}
    assert detail.get("fact_count") == 2
    assert detail.get("facts") == [
        {"text": "事实甲在这里", "source": "文档 A"},
        {"text": "事实乙在这里", "source": ""},
    ]


def test_medium_result_carries_structured_fact_detail(monkeypatch):
    """run_plan_preflight 返回值带 scout_facts_detail —— 供前端展示与落库。"""
    classifier_module = _patch_common(monkeypatch)

    async def fake_classify(message, context=None):
        return ComplexityClassification(
            complexity="medium", research_needed=True, reasoning=""
        )

    async def fake_clarify(client, message, emit):
        return []

    async def fake_scout(
        client, message, emit, clarifications, max_iterations=3, fallback_client=None
    ):
        return "- 事实甲在这里（来源：文档 A）\n- 事实乙在这里"

    monkeypatch.setattr(classifier_module, "classify_complexity", fake_classify)
    monkeypatch.setattr(plan_preflight, "_clarify", fake_clarify)
    monkeypatch.setattr(plan_preflight, "_scout", fake_scout)

    events, emit = _collect()
    result = asyncio.run(plan_preflight.run_plan_preflight("重构模块", emit=emit))

    assert result is not None
    detail = result["scout_facts_detail"]
    assert detail["fact_count"] == 2
    assert detail["facts"] == [
        {"text": "事实甲在这里", "source": "文档 A"},
        {"text": "事实乙在这里", "source": ""},
    ]
    # 原文那份同时保留 —— planner 靠它做拆解
    assert "事实甲在这里" in result["scout_facts"]


def test_scout_deep_success_does_not_emit_fact_detail(monkeypatch):
    """scout_deep 成功 → 不产出 scout_facts_detail（调研报告走 ResearchSummaryCard）。

    scout_deep 成功时 ``scout_facts`` 装的是调研报告上下文（语义与 lite scout
    的事实清单不同），若复用同一键会把调研内容误标成事实清单。
    """
    import backend.orchestration.scout_deep as scout_deep_module

    classifier_module = _patch_common(monkeypatch)

    async def fake_classify(message, context=None):
        return ComplexityClassification(
            complexity="complex", research_needed=True, reasoning=""
        )

    async def fake_clarify(client, message, emit):
        return []

    class _FakeReport:
        confidence = 0.8
        findings = ["发现一"]

        def to_dict(self):
            return {"confidence": 0.8, "findings": ["发现一"]}

        def to_planner_context(self, limit):
            return "调研报告上下文"

    async def fake_research(**kwargs):
        return _FakeReport()

    monkeypatch.setattr(classifier_module, "classify_complexity", fake_classify)
    monkeypatch.setattr(plan_preflight, "_clarify", fake_clarify)
    monkeypatch.setattr(scout_deep_module, "research", fake_research)

    events, emit = _collect()
    result = asyncio.run(plan_preflight.run_plan_preflight("复杂调研", emit=emit))

    assert result is not None
    assert "scout_facts_detail" not in result, (
        "scout_deep 成功时不应产出 lite scout 的事实清单"
    )
    assert result["scout_facts"] == "调研报告上下文"


def test_scout_event_to_progress_maps_thinking_and_tool():
    from backend.orchestration.plan_preflight import _scout_event_to_progress

    assert _scout_event_to_progress(
        AgentEvent(state=AgentState.REASONING, reasoning="分析中")
    ) == {"kind": "thinking", "text": "分析中"}
    assert _scout_event_to_progress(
        AgentEvent(state=AgentState.REASONING_DELTA, reasoning="增量")
    ) == {"kind": "thinking", "text": "增量"}
    # THINKING 是裸阶段标记（无 reasoning/content），不应产生进度条目
    assert _scout_event_to_progress(AgentEvent(state=AgentState.THINKING)) is None
    assert _scout_event_to_progress(
        AgentEvent(
            state=AgentState.ACTING,
            tool_call=ToolCallRequest(id="1", name="read_file", arguments={}),
        )
    ) == {"kind": "tool_call", "text": "read_file"}
    assert _scout_event_to_progress(
        AgentEvent(
            state=AgentState.OBSERVING,
            tool_result=ToolCallResult(tool_call_id="1", content="ok"),
        )
    ) == {"kind": "tool_result", "text": "工具返回结果"}
    assert _scout_event_to_progress(
        AgentEvent(state=AgentState.DONE, content="x")
    ) is None


def test_run_scout_agent_emits_thinking_and_tool_progress(monkeypatch):
    """_run_scout_agent 把子代理 thinking/tool 事件作为 plan_progress 透出。"""
    import backend.core.legacy.agent as agent_module
    import backend.tools.agent_tool as agent_tool_module

    class _FakeSageAgent:
        def __init__(self, bare=False):
            self.tool_registry = None
            self._owned_workspace_root = None
            self.llm_client = None

        async def run_loop(self, messages, max_iterations=3):
            yield AgentEvent(state=AgentState.REASONING, reasoning="分析中")
            yield AgentEvent(
                state=AgentState.ACTING,
                tool_call=ToolCallRequest(id="1", name="read_file", arguments={}),
            )
            yield AgentEvent(
                state=AgentState.OBSERVING,
                tool_result=ToolCallResult(tool_call_id="1", content="ok"),
            )
            yield AgentEvent(state=AgentState.DONE, content="最终答案")

    monkeypatch.setattr(agent_module, "SageAgent", _FakeSageAgent)
    monkeypatch.setattr(
        agent_tool_module,
        "build_readonly_tool_registry",
        lambda: types.SimpleNamespace(_owned_workspace_root=None),
    )
    monkeypatch.setattr(
        agent_tool_module, "_cleanup_subagent_workspace", lambda *a, **k: None
    )

    collected = []

    async def emit(envelope):
        collected.append(envelope)

    answer = asyncio.run(
        plan_preflight._run_scout_agent(object(), "goal", emit=emit)
    )

    assert answer == "最终答案"
    progresses = [
        e["plan_progress"] for e in collected if e["state"] == "plan_progress"
    ]
    assert all(
        p["stage"] == "scout" and p["status"] == "progress" for p in progresses
    )
    assert any(
        p["kind"] == "thinking" and p["text"] == "分析中" for p in progresses
    )
    assert any(
        p["kind"] == "tool_call" and p["text"] == "read_file" for p in progresses
    )


# ---------------------------------------------------------------------------
# HIGH 2: _scout 普通客户端回退
# ---------------------------------------------------------------------------


def test_scout_retries_with_fallback_client_on_failure(monkeypatch):
    """首客户端非超时失败 → 用 fallback_client 再试一次并返回其事实。"""
    calls = []

    async def fake_run_agent(client, goal, max_iterations=3, emit=None):
        calls.append(client)
        if client == "bad":
            raise RuntimeError("thinking_effort unsupported")
        return "- fact from fallback"

    monkeypatch.setattr(plan_preflight, "_run_scout_agent", fake_run_agent)
    _, emit = _collect()

    facts = asyncio.run(
        plan_preflight._scout(
            "bad", "goal", emit, [], max_iterations=3, fallback_client="good"
        )
    )
    assert facts == "- fact from fallback"
    assert calls == ["bad", "good"]


def test_scout_returns_empty_when_both_clients_fail(monkeypatch):
    """回退也失败 → 返回空串（跳过事实注入，不阻塞拆解）。"""

    async def fake_run_agent(client, goal, max_iterations=3, emit=None):
        raise RuntimeError("down")

    monkeypatch.setattr(plan_preflight, "_run_scout_agent", fake_run_agent)
    _, emit = _collect()

    facts = asyncio.run(
        plan_preflight._scout("bad", "goal", emit, [], fallback_client="good")
    )
    assert facts == ""


def test_scout_without_fallback_returns_empty(monkeypatch):
    """未提供 fallback_client → 首客户端失败即返回空串，不再重试。"""
    calls = []

    async def fake_run_agent(client, goal, max_iterations=3, emit=None):
        calls.append(client)
        raise RuntimeError("down")

    monkeypatch.setattr(plan_preflight, "_run_scout_agent", fake_run_agent)
    _, emit = _collect()

    facts = asyncio.run(plan_preflight._scout("only", "goal", emit, []))
    assert facts == ""
    assert calls == ["only"]


# ---------------------------------------------------------------------------
# MEDIUM 3: _run_scout_agent 思考节流
# ---------------------------------------------------------------------------


def _patch_scout_agent(monkeypatch, events):
    """把 SageAgent.run_loop 替换为固定事件序列，并屏蔽只读注册表清理。"""
    import backend.core.legacy.agent as agent_module
    import backend.tools.agent_tool as agent_tool_module

    class _FakeSageAgent:
        def __init__(self, bare=False):
            self.tool_registry = None
            self._owned_workspace_root = None
            self.llm_client = None

        async def run_loop(self, messages, max_iterations=3):
            for event in events:
                yield event

    monkeypatch.setattr(agent_module, "SageAgent", _FakeSageAgent)
    monkeypatch.setattr(
        agent_tool_module,
        "build_readonly_tool_registry",
        lambda: types.SimpleNamespace(_owned_workspace_root=None),
    )
    monkeypatch.setattr(
        agent_tool_module, "_cleanup_subagent_workspace", lambda *a, **k: None
    )


def _collect_scout_progress():
    collected = []

    async def emit(envelope):
        collected.append(envelope)

    asyncio.run(plan_preflight._run_scout_agent(object(), "goal", emit=emit))
    return [
        e["plan_progress"] for e in collected if e["state"] == "plan_progress"
    ]


def test_run_scout_agent_throttles_rapid_thinking(monkeypatch):
    """高频重复思考被间隔节流 + 去重 → 仅推送 1 条。"""
    events = [
        AgentEvent(state=AgentState.REASONING, reasoning="分析中") for _ in range(5)
    ] + [AgentEvent(state=AgentState.DONE, content="完成")]
    _patch_scout_agent(monkeypatch, events)

    progresses = _collect_scout_progress()
    thinking = [p for p in progresses if p["kind"] == "thinking"]
    assert len(thinking) == 1


def test_run_scout_agent_dedupes_identical_thinking(monkeypatch):
    """间隔置 0 时仍跳过与上一条相同的思考文本。"""
    monkeypatch.setattr(plan_preflight, "SCOUT_THINKING_MIN_INTERVAL_S", 0.0)
    events = [
        AgentEvent(state=AgentState.REASONING, reasoning="分析中"),
        AgentEvent(state=AgentState.REASONING, reasoning="分析中"),
        AgentEvent(state=AgentState.REASONING, reasoning="新分析"),
        AgentEvent(state=AgentState.REASONING, reasoning="新分析"),
        AgentEvent(state=AgentState.DONE, content="完成"),
    ]
    _patch_scout_agent(monkeypatch, events)

    progresses = _collect_scout_progress()
    thinking = [p["text"] for p in progresses if p["kind"] == "thinking"]
    assert thinking == ["分析中", "新分析"]


def test_run_scout_agent_caps_thinking_emits(monkeypatch):
    """整轮思考推送条数受 SCOUT_THINKING_MAX_EMITS 封顶。"""
    monkeypatch.setattr(plan_preflight, "SCOUT_THINKING_MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(plan_preflight, "SCOUT_THINKING_MAX_EMITS", 2)
    events = [
        AgentEvent(state=AgentState.REASONING, reasoning=f"想法{i}") for i in range(5)
    ] + [AgentEvent(state=AgentState.DONE, content="完成")]
    _patch_scout_agent(monkeypatch, events)

    progresses = _collect_scout_progress()
    thinking = [p for p in progresses if p["kind"] == "thinking"]
    assert len(thinking) == 2
    assert [p["text"] for p in thinking] == ["想法0", "想法1"]

