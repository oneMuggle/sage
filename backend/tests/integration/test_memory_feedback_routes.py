# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""Task 4.5 —— /memory/{memory_id}/feedback 集成测试。

覆盖:
- POST 成功写入 up / down / neutral 并可在 list 的 user_feedback 字段观察到
- 重复提交覆盖（up → down）
- reason 持久化
- 404: 不存在的记忆 id
- 422: 非法 feedback 值（pydantic pattern）
- 405 范围外: 不存在的 memory_type（pydantic pattern）
- 工作记忆 (working) 与 session_summary 行 list 不查反馈表、user_feedback=None
- episodic 软删除后 is_valid=0 → 反馈写入应 404
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"


async def _save_episodic(client, content: str, importance: int = 5) -> str:
    resp = await client.post(
        f"{PREFIX}/memory/save",
        json={"content": content, "memory_type": "episodic", "importance": importance},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


# ---------- 写入 / 覆盖 ----------


@pytest.mark.asyncio()
async def test_up_feedback_persists_and_appears_in_list(client):
    memory_id = await _save_episodic(client, "用户偏好 Python 3.10")

    resp = await client.post(
        f"{PREFIX}/memory/{memory_id}/feedback",
        json={"feedback": "up"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "status": "ok",
        "memory_id": memory_id,
        "memory_type": "episodic",
        "feedback": "up",
    }

    # list 的同一行应出现 user_feedback = "up"
    list_resp = await client.get(
        f"{PREFIX}/memory/list", params={"type": "episodic", "page_size": 20}
    )
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    by_id = {i["id"]: i for i in items}
    assert memory_id in by_id
    assert by_id[memory_id]["user_feedback"] == "up"


@pytest.mark.asyncio()
async def test_repeat_submit_overwrites_feedback(client):
    memory_id = await _save_episodic(client, "覆盖测试记忆")

    resp1 = await client.post(
        f"{PREFIX}/memory/{memory_id}/feedback",
        json={"feedback": "up"},
    )
    assert resp1.status_code == 200
    resp2 = await client.post(
        f"{PREFIX}/memory/{memory_id}/feedback",
        json={"feedback": "down", "reason": "内容过时"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["feedback"] == "down"

    list_resp = await client.get(
        f"{PREFIX}/memory/list", params={"type": "episodic"}
    )
    items = list_resp.json()["items"]
    by_id = {i["id"]: i for i in items}
    assert by_id[memory_id]["user_feedback"] == "down"

    # 直接查表验证 reason 持久化
    from backend.memory import get_memory_manager
    from backend.memory.feedback_store import get_feedback

    mm = get_memory_manager()
    info = get_feedback(mm.episodic.db, memory_id, "episodic")
    assert info is not None
    assert info["feedback"] == "down"
    assert info["reason"] == "内容过时"


@pytest.mark.asyncio()
async def test_neutral_feedback_accepted(client):
    memory_id = await _save_episodic(client, "中性反馈记忆")
    resp = await client.post(
        f"{PREFIX}/memory/{memory_id}/feedback",
        json={"feedback": "neutral"},
    )
    assert resp.status_code == 200
    assert resp.json()["feedback"] == "neutral"


# ---------- 错误路径 ----------


@pytest.mark.asyncio()
async def test_feedback_to_nonexistent_memory_returns_404(client):
    resp = await client.post(
        f"{PREFIX}/memory/00000000-0000-0000-0000-000000000000/feedback",
        json={"feedback": "up"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio()
async def test_feedback_invalid_value_rejected(client):
    memory_id = await _save_episodic(client, "非法反馈测试")
    resp = await client.post(
        f"{PREFIX}/memory/{memory_id}/feedback",
        json={"feedback": "sideways"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio()
async def test_feedback_invalid_memory_type_rejected(client):
    memory_id = await _save_episodic(client, "非法类型测试")
    resp = await client.post(
        f"{PREFIX}/memory/{memory_id}/feedback",
        json={"feedback": "up", "memory_type": "working"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio()
async def test_feedback_to_soft_deleted_episodic_returns_404(client):
    memory_id = await _save_episodic(client, "待删除记忆")
    # 软删除 (is_valid=0)
    from backend.memory import get_memory_manager
    mm = get_memory_manager()
    assert mm.delete_memory(memory_id, "episodic") is True

    resp = await client.post(
        f"{PREFIX}/memory/{memory_id}/feedback",
        json={"feedback": "up"},
    )
    assert resp.status_code == 404


# ---------- list 兜底 ----------


@pytest.mark.asyncio()
async def test_working_memory_rows_get_null_user_feedback(client):
    # working memory 来自 in-memory deque，list 的 attach_feedback 必须
    # 默认填 None，不查表也不报错
    from backend.memory import get_memory_manager

    mm = get_memory_manager()
    mm.working.add(
        session_id="sess-feedback-test",
        message={"role": "user", "content": "测试工作记忆"},
    )

    list_resp = await client.get(
        f"{PREFIX}/memory/list", params={"type": "working"}
    )
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert items, "预期至少一条工作记忆"
    assert all(item["user_feedback"] is None for item in items)
