"""M2 part B — UserQuestionGate 单测。

覆盖: 应答解析 Future、未知 id、超时返回空应答、pending 快照、
单例访问器、QuestionRequest.to_dict 前端契约形态。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.services.question_gate import (
    QuestionAnswer,
    QuestionRequest,
    UserQuestionGate,
    get_question_gate,
    init_question_gate,
    reset_question_gate,
)

pytestmark = pytest.mark.unit

OPTIONS = (
    {"label": "Markdown", "description": "纯文本报告"},
    {"label": "PDF", "description": "排版文档"},
)


@pytest.fixture(autouse=True)
def _clean_global_gate():
    """每个测试前后重置全局 gate, 避免跨测试泄漏。"""
    reset_question_gate()
    yield
    reset_question_gate()


def _make_request(question: str = "选择输出格式") -> QuestionRequest:
    return QuestionRequest.create(
        question=question, options=list(OPTIONS), header="输出格式", multi_select=False
    )


# ---------------------------------------------------------------------------
# Future 解析
# ---------------------------------------------------------------------------


async def test_gate_answer_resolves_pending_request_future():
    """并发任务调用 answer() → request() 的 await 解析为 gui 应答。"""
    # Arrange
    gate = UserQuestionGate()
    req = _make_request()

    async def answer_later():
        await asyncio.sleep(0.01)
        assert gate.answer(req.request_id, answers=["PDF"], custom=None) is True

    # Act
    task = asyncio.create_task(answer_later())
    answer = await gate.request(req, timeout=5.0)
    await task

    # Assert
    assert answer.answers == ("PDF",)
    assert answer.custom is None
    assert answer.answered_by == "gui"


async def test_gate_answer_with_multi_select_and_custom():
    """多选 + 自由文本一并透传。"""
    # Arrange
    gate = UserQuestionGate()
    req = QuestionRequest.create(
        question="选哪些?", options=list(OPTIONS), multi_select=True
    )

    async def answer_later():
        await asyncio.sleep(0.01)
        gate.answer(req.request_id, answers=["Markdown", "PDF"], custom="都要")

    # Act
    task = asyncio.create_task(answer_later())
    answer = await gate.request(req, timeout=5.0)
    await task

    # Assert
    assert answer.answers == ("Markdown", "PDF")
    assert answer.custom == "都要"
    assert answer.answered_by == "gui"


def test_gate_answer_unknown_id_returns_false():
    """未知 request_id → False (路由层转成 unknown_or_expired)。"""
    # Arrange
    gate = UserQuestionGate()

    # Act / Assert
    assert gate.answer("no-such-id", answers=["x"]) is False


async def test_gate_answer_after_expiry_returns_false():
    """超时清理后, 迟到的 answer() → False。"""
    # Arrange
    gate = UserQuestionGate()
    req = _make_request()

    # Act —— 极短超时让请求过期
    answer = await gate.request(req, timeout=0.05)
    late = gate.answer(req.request_id, answers=["PDF"])

    # Assert
    assert answer.answers == ()
    assert answer.custom is None
    assert answer.answered_by == "timeout"
    assert late is False


async def test_gate_timeout_returns_empty_answer_without_hanging():
    """无应答超时 → 空应答（fail-open-ish，agent 继续而非挂死）。"""
    # Arrange
    gate = UserQuestionGate()
    req = _make_request()

    # Act
    answer = await gate.request(req, timeout=0.05)

    # Assert
    assert isinstance(answer, QuestionAnswer)
    assert answer.answers == ()
    assert answer.custom is None
    assert answer.answered_by == "timeout"


async def test_gate_double_answer_second_call_returns_false():
    """同一请求被应答两次 → 第二次 False。"""
    # Arrange
    gate = UserQuestionGate()
    req = _make_request()

    async def answer_twice():
        await asyncio.sleep(0.01)
        assert gate.answer(req.request_id, answers=["PDF"]) is True
        assert gate.answer(req.request_id, answers=["Markdown"]) is False

    # Act
    task = asyncio.create_task(answer_twice())
    await gate.request(req, timeout=5.0)
    await task


# ---------------------------------------------------------------------------
# pending / get_request
# ---------------------------------------------------------------------------


async def test_gate_pending_lists_only_unanswered_requests():
    """pending() 只返回未应答请求; 应答后即消失。"""
    # Arrange
    gate = UserQuestionGate()
    r1 = _make_request("q1")
    r2 = _make_request("q2")

    async def answer_one():
        for _ in range(200):
            if gate.get_request(r1.request_id) is not None:
                break
            await asyncio.sleep(0.005)
        gate.answer(r1.request_id, answers=["PDF"])

    task = asyncio.create_task(answer_one())
    r2_holder = asyncio.create_task(gate.request(r2, timeout=0.05))
    await gate.request(r1, timeout=5.0)

    # Assert
    pending_ids = [r.request_id for r in gate.pending()]
    assert r1.request_id not in pending_ids
    assert r2.request_id in pending_ids
    await r2_holder
    await task
    assert gate.pending() == []


def test_gate_get_request_returns_none_for_unknown():
    """get_request 未知 id → None。"""
    # Arrange
    gate = UserQuestionGate()

    # Act / Assert
    assert gate.get_request("nope") is None


# ---------------------------------------------------------------------------
# 单例访问器
# ---------------------------------------------------------------------------


def test_global_gate_none_until_initialized():
    """未 init 时 get_question_gate() → None（调用方按无人应答处理）。"""
    # Arrange / Act / Assert
    assert get_question_gate() is None


def test_init_question_gate_returns_singleton():
    """init 后 get 返回同一实例。"""
    # Arrange / Act
    gate = init_question_gate()

    # Assert
    assert get_question_gate() is gate
    assert init_question_gate() is not gate  # 再次 init 会替换实例


# ---------------------------------------------------------------------------
# QuestionRequest 序列化契约
# ---------------------------------------------------------------------------


def test_question_request_to_dict_shape_matches_frontend_contract():
    """to_dict 的键集合是前端契约——改动需同步前端 agent。"""
    # Arrange
    req = _make_request()

    # Act
    payload = req.to_dict()

    # Assert
    assert set(payload.keys()) == {
        "request_id",
        "question",
        "header",
        "options",
        "multi_select",
        "created_at",
    }
    assert payload["question"] == "选择输出格式"
    assert payload["header"] == "输出格式"
    assert payload["multi_select"] is False
    assert payload["options"] == [
        {"label": "Markdown", "description": "纯文本报告"},
        {"label": "PDF", "description": "排版文档"},
    ]
    assert isinstance(payload["created_at"], float)


def test_question_request_create_normalizes_options():
    """工厂规范化选项（description 缺省 None）。"""
    # Arrange / Act
    req = QuestionRequest.create(
        question="q",
        options=[{"label": "A"}, {"label": "B", "description": "b"}],
    )

    # Assert
    assert req.options == (
        {"label": "A", "description": None},
        {"label": "B", "description": "b"},
    )
