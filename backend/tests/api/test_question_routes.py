"""M2 part B — /api/v1/questions REST 契约测试。

覆盖:
- GET /pending 返回挂起提问的 JSON 契约（含 gate 未初始化空列表）
- POST /{id}/answer 成功（含 custom）/ 未知 id / gate 未初始化
- 请求体非法 → 422 (pydantic extra=forbid)
- Origin 守卫: 恶意 Origin 403 / 白名单 Origin 放行 / 无 Origin 放行
"""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from backend.services.question_gate import (
    QuestionRequest,
    init_question_gate,
    reset_question_gate,
)

pytestmark = pytest.mark.unit  # 走 ASGITransport 直连 app, 属快测

OPTIONS = [{"label": "Markdown"}, {"label": "PDF"}]


@pytest.fixture()
def gate():
    """每个测试初始化独立 gate, 结束重置。"""
    reset_question_gate()
    g = init_question_gate()
    yield g
    reset_question_gate()


def _pending_request(question: str = "选择输出格式") -> QuestionRequest:
    return QuestionRequest.create(
        question=question, options=OPTIONS, header="输出格式", multi_select=False
    )


async def test_get_pending_returns_empty_list_when_gate_uninitialized(client):
    """gate 未初始化 → GET /pending 返回空列表而非 500。"""
    # Arrange
    reset_question_gate()

    # Act
    resp = await client.get("/api/v1/questions/pending")

    # Assert
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_pending_returns_registered_requests(gate, client):
    """挂起提问出现在 /pending, 字段形态符合前端契约。"""
    # Arrange
    req = _pending_request()
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)  # 等注册完成

    # Act
    resp = await client.get("/api/v1/questions/pending")

    # Assert
    assert resp.status_code == 200
    items: List[dict] = resp.json()
    assert len(items) == 1
    item = items[0]
    assert item["request_id"] == req.request_id
    assert item["question"] == "选择输出格式"
    assert item["header"] == "输出格式"
    assert item["multi_select"] is False
    assert [opt["label"] for opt in item["options"]] == ["Markdown", "PDF"]
    assert isinstance(item["created_at"], float)

    # 清理 —— 应答掉挂起请求
    gate.answer(req.request_id, answers=[])
    await holder


async def test_post_answer_resolves_gate_future_with_selection(gate, client):
    """POST answer → ok, gate 的 request() 解析为携带选择的应答。"""
    # Arrange
    req = _pending_request()
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    # Act
    resp = await client.post(
        f"/api/v1/questions/{req.request_id}/answer",
        json={"answers": ["PDF"], "custom": None},
    )
    answer = await holder

    # Assert
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert answer.answers == ("PDF",)
    assert answer.custom is None
    assert answer.answered_by == "gui"


async def test_post_answer_with_custom_text(gate, client):
    """custom 自由文本随应答透传。"""
    # Arrange
    req = _pending_request()
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    # Act
    resp = await client.post(
        f"/api/v1/questions/{req.request_id}/answer",
        json={"answers": [], "custom": "用 HTML"},
    )
    answer = await holder

    # Assert
    assert resp.json() == {"ok": True}
    assert answer.answers == ()
    assert answer.custom == "用 HTML"


async def test_post_answer_empty_body_defaults_to_empty_selection(gate, client):
    """空 body（answers 默认 []）合法 —— Escape 空提交 = 超时语义。"""
    # Arrange
    req = _pending_request()
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    # Act
    resp = await client.post(f"/api/v1/questions/{req.request_id}/answer", json={})
    answer = await holder

    # Assert
    assert resp.json() == {"ok": True}
    assert answer.answers == ()
    assert answer.custom is None


async def test_post_answer_unknown_id_returns_ok_false(gate, client):
    """未知 request_id → {"ok": false, "error": "unknown_or_expired"}。"""
    # Arrange / Act
    resp = await client.post(
        "/api/v1/questions/no-such-id/answer",
        json={"answers": ["PDF"]},
    )

    # Assert
    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "error": "unknown_or_expired"}


async def test_post_answer_when_gate_uninitialized_returns_ok_false(client):
    """gate 未初始化 → {"ok": false, "error": "question_gate_not_initialized"}。"""
    # Arrange
    reset_question_gate()

    # Act
    resp = await client.post(
        "/api/v1/questions/whatever/answer", json={"answers": ["PDF"]}
    )

    # Assert
    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "error": "question_gate_not_initialized"}


async def test_post_answer_rejects_extra_body_fields(gate, client):
    """extra=forbid: 未知字段 → 422。"""
    # Arrange / Act
    resp = await client.post(
        "/api/v1/questions/x/answer",
        json={"answers": ["PDF"], "hacker_field": 1},
    )

    # Assert
    assert resp.status_code == 422


async def test_post_answer_rejects_wrong_answers_type(gate, client):
    """answers 非列表 → 422。"""
    # Arrange / Act
    resp = await client.post(
        "/api/v1/questions/x/answer",
        json={"answers": "PDF"},
    )

    # Assert
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Origin 守卫（复用 permission_routes 的同一实现）
# ---------------------------------------------------------------------------


async def test_answer_with_evil_origin_returns_403(gate, client):
    """带第三方网页 Origin 的 POST answer → 403 forbidden_origin。"""
    # Arrange / Act
    resp = await client.post(
        "/api/v1/questions/whatever/answer",
        json={"answers": ["PDF"]},
        headers={"Origin": "https://evil.com"},
    )

    # Assert
    assert resp.status_code == 403
    assert resp.json() == {"ok": False, "error": "forbidden_origin"}


async def test_answer_with_allowed_dev_origin_passes(gate, client):
    """Electron 开发 Origin (http://localhost:1420) → 200 正常应答。"""
    # Arrange
    req = _pending_request()
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    # Act
    resp = await client.post(
        f"/api/v1/questions/{req.request_id}/answer",
        json={"answers": ["Markdown"]},
        headers={"Origin": "http://localhost:1420"},
    )
    answer = await holder

    # Assert
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert answer.answers == ("Markdown",)


async def test_answer_without_origin_header_passes(gate, client):
    """无 Origin 头（同源 / curl / python）→ 放行, 走正常错误语义。"""
    # Arrange / Act
    resp = await client.post(
        "/api/v1/questions/whatever/answer", json={"answers": ["PDF"]}
    )

    # Assert — 放行到业务层, 未知 id 返回 ok=false 而不是 403
    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "error": "unknown_or_expired"}


async def test_get_pending_with_evil_origin_returns_403(gate, client):
    """GET /pending 同样受 Origin 守卫保护。"""
    # Arrange / Act
    resp = await client.get(
        "/api/v1/questions/pending", headers={"Origin": "https://evil.com"}
    )

    # Assert
    assert resp.status_code == 403
    assert resp.json() == {"ok": False, "error": "forbidden_origin"}


async def test_get_pending_with_file_origin_passes(gate, client):
    """打包 Electron 的 file:// Origin → 200。"""
    # Arrange / Act
    resp = await client.get("/api/v1/questions/pending", headers={"Origin": "file://"})

    # Assert
    assert resp.status_code == 200
    assert resp.json() == []
