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

    async def fake_scout(client, message, emit, clarifications, max_iterations=3):
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

