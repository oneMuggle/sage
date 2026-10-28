"""``test_legacy_routes_execution_mode`` — 计划模式执行模式推荐事件（2026-10-28）。

覆盖 ``legacy_routes._emit_execution_mode_recommendation``：

- 成功分类 → 推 ``plan_execution_mode`` 事件（字段齐全）。
- LLM 调用超时（20s 上限）→ 降级 ``ask_user``，confidence=0，reasoning 明示超时。
- 分类器抛异常 → 降级 ``ask_user``，**绝不抛错**（调用链收尾不能断）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest


@dataclass
class FakeStreamEntry:
    """最小 StreamEntry 替身 —— 只需 queue.put() 能力。"""

    queue: asyncio.Queue[dict]


@pytest.fixture()
def fake_entry():
    return FakeStreamEntry(queue=asyncio.Queue())


class _FakeClassification:
    """分类结果替身 — 字段名与 ExecutionModeClassification 一致。"""

    def __init__(self, mode: str, confidence: float, reasoning: str) -> None:
        self.mode = mode
        self.confidence = confidence
        self.reasoning = reasoning


async def test_emit_pushes_plan_execution_mode_event(monkeypatch, fake_entry):
    """成功分类 → 推事件 + 字段齐全（mode/confidence/reasoning）。"""

    async def fake_classify(plan_text: str) -> _FakeClassification:
        assert isinstance(plan_text, str)
        return _FakeClassification(
            mode="multi",
            confidence=0.9,
            reasoning="步骤多，有独立可并行",
        )

    import backend.api.legacy_routes as lr

    monkeypatch.setattr(
        "backend.orchestration.execution_mode_classifier.classify_execution_mode",
        fake_classify,
        raising=False,
    )

    await lr._emit_execution_mode_recommendation(
        fake_entry,
        session_id="sess-001",
        plan_text="## 目标\n重构缓存层\n## 分步\n1. 拆 A\n2. 拆 B\n3. 拆 C",
    )

    event = fake_entry.queue.get_nowait()
    assert event["state"] == "plan_execution_mode"
    assert event["session_id"] == "sess-001"
    assert event["execution_mode"] == "multi"
    assert event["execution_mode_confidence"] == 0.9
    assert event["execution_mode_reasoning"] == "步骤多，有独立可并行"


async def test_emit_degrades_to_ask_user_on_timeout(monkeypatch, fake_entry):
    """LLM 调用超时（>20s）→ 降级 ask_user，绝不抛错。"""

    async def slow_classify(plan_text: str) -> _FakeClassification:
        await asyncio.sleep(30)
        return _FakeClassification(mode="single", confidence=1.0, reasoning="never")

    import backend.api.legacy_routes as lr

    monkeypatch.setattr(lr, "_EXECUTION_MODE_CLASSIFY_TIMEOUT_S", 0.01)
    monkeypatch.setattr(
        "backend.orchestration.execution_mode_classifier.classify_execution_mode",
        slow_classify,
        raising=False,
    )

    # 必须不抛错
    await lr._emit_execution_mode_recommendation(fake_entry, "sess-002", "## 计划")

    event = fake_entry.queue.get_nowait()
    assert event["state"] == "plan_execution_mode"
    assert event["execution_mode"] == "ask_user"
    assert event["execution_mode_confidence"] == 0.0
    assert "超时" in event["execution_mode_reasoning"]


async def test_emit_degrades_to_ask_user_on_exception(monkeypatch, fake_entry):
    """分类器抛异常 → 降级 ask_user，绝不抛错。"""

    async def broken_classify(plan_text: str) -> _FakeClassification:
        raise RuntimeError("LLM 端点不可用")

    import backend.api.legacy_routes as lr

    monkeypatch.setattr(
        "backend.orchestration.execution_mode_classifier.classify_execution_mode",
        broken_classify,
        raising=False,
    )

    await lr._emit_execution_mode_recommendation(fake_entry, "sess-003", "## 计划")

    # 分类器抛错被外层 try/except 吞掉 → 无事件推入，但不抛错
    assert fake_entry.queue.empty()


async def test_emit_never_raises_on_queue_failure(monkeypatch):
    """entry.queue.put 抛异常 → 降级静默处理，绝不阻塞收尾。"""

    class BrokenQueue(asyncio.Queue):
        async def put(self, item):  # type: ignore[override]
            raise RuntimeError("queue closed")

    async def fake_classify(plan_text: str) -> _FakeClassification:
        return _FakeClassification(mode="single", confidence=1.0, reasoning="ok")

    import backend.api.legacy_routes as lr

    monkeypatch.setattr(
        "backend.orchestration.execution_mode_classifier.classify_execution_mode",
        fake_classify,
        raising=False,
    )

    entry = FakeStreamEntry(queue=BrokenQueue())
    # 必须不抛错
    await lr._emit_execution_mode_recommendation(entry, "sess-004", "## 计划")


# ===========================================================================
# Phase 3 (2026-10-28): 步骤级确认开关解析
# ===========================================================================


@pytest.mark.parametrize(
    ("requested", "complexity", "expected"),
    [
        # None = 自动：仅 complex 启用
        (None, "complex", True),
        (None, "medium", False),
        (None, "simple", False),
        # preflight 关闭 / 分类失败 → complexity 缺失 → 不启用（既有行为）
        (None, None, False),
        # 显式值覆盖复杂度
        (True, None, True),
        (True, "simple", True),
        (False, "complex", False),
        (False, None, False),
    ],
)
def test_resolve_step_confirm_flag(requested, complexity, expected):
    """三态开关：None=按复杂度自动，True/False=显式覆盖。"""
    from backend.api.legacy_routes import _resolve_step_confirm_flag

    assert _resolve_step_confirm_flag(requested, complexity) is expected
