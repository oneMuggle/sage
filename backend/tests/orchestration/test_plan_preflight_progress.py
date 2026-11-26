import asyncio

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

    ``plan_preflight`` 在函数体内惰性 import ``build_llm_client_from_settings``，
    所以必须 patch ``llm_factory`` 模块属性而非 ``plan_preflight`` 上的名字；
    ``classify_complexity`` 同理。
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
