"""R173 — 用户提问 REST 路由单元测试。

覆盖：list_pending（gate 未初始化 / 有挂起）、origin 守卫 403、answer
错误映射（gate 未初始化 / unknown_or_expired / 正常 ok）、
QuestionAnswerBody extra=forbid。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.api import question_routes as qr
from backend.api.question_routes import QuestionAnswerBody

pytestmark = pytest.mark.unit


class _FakeRequest:
    pass


@pytest.fixture(autouse=True)
def _allow_origin(monkeypatch):
    monkeypatch.setattr(qr, "forbidden_origin_response", lambda request: None)


def _patch_gate(monkeypatch, gate):
    monkeypatch.setattr(qr, "get_question_gate", lambda: gate)


# ---------------------------------------------------------------------------
# GET /pending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_pending_gate_none_returns_empty(monkeypatch):
    _patch_gate(monkeypatch, None)
    assert await qr.list_pending_questions(_FakeRequest()) == []


@pytest.mark.asyncio()
async def test_pending_returns_dicts(monkeypatch):
    gate = SimpleNamespace(
        pending=lambda: [
            SimpleNamespace(to_dict=lambda: {"id": "q1", "question": "选择"}),
            SimpleNamespace(to_dict=lambda: {"id": "q2", "question": "确认"}),
        ]
    )
    _patch_gate(monkeypatch, gate)
    out = await qr.list_pending_questions(_FakeRequest())
    assert len(out) == 2
    assert out[0]["id"] == "q1"


# ---------------------------------------------------------------------------
# POST answer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_answer_gate_none_returns_error(monkeypatch):
    _patch_gate(monkeypatch, None)
    out = await qr.answer_question("q1", QuestionAnswerBody(answers=["a"]), _FakeRequest())
    assert out == {"ok": False, "error": "question_gate_not_initialized"}


@pytest.mark.asyncio()
async def test_answer_unknown_or_expired(monkeypatch):
    gate = SimpleNamespace(answer=lambda rid, answers, custom: None)
    _patch_gate(monkeypatch, gate)
    out = await qr.answer_question("ghost", QuestionAnswerBody(answers=["a"]), _FakeRequest())
    assert out == {"ok": False, "error": "unknown_or_expired"}


@pytest.mark.asyncio()
async def test_answer_success_ok_true(monkeypatch):
    gate = SimpleNamespace(answer=lambda rid, answers, custom: True)
    _patch_gate(monkeypatch, gate)
    out = await qr.answer_question(
        "q1", QuestionAnswerBody(answers=["opt1"], custom="自由文本"), _FakeRequest()
    )
    assert out == {"ok": True}


def test_answer_body_extra_forbid():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        QuestionAnswerBody(answers=["a"], unknown_field="x")


# ---------------------------------------------------------------------------
# origin 守卫
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_origin_guard_403_passthrough(monkeypatch):
    resp = SimpleNamespace(status_code=403)
    monkeypatch.setattr(qr, "forbidden_origin_response", lambda request: resp)
    assert await qr.list_pending_questions(_FakeRequest()) is resp
    assert await qr.answer_question("q1", QuestionAnswerBody(), _FakeRequest()) is resp
