"""RT5 (round7) + 2026-11-07 steer-staging-panel — 单 agent steering 测试。

覆盖三层：
- agent 层：inject_user_message 的运行窗口语义 + run_loop 迭代边界消费
  + 迭代边界上下文预算复核（插话计入高水位，反证对照）
  + 新增：撤回未消费插话 / 队列形态（dict {id, text}） / STEER_CONSUMED 事件
- 端点层：POST /api/v1/chat/steer 的 200/404/409/400 面
  + 新增：响应带 message_id；消费回执（drain 触发落库）
- 端点层：POST /api/v1/chat/steer/cancel —— 撤回未消费插话；已被消费/流已结束
  时返回 removed=False
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import ASGITransport

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall

pytestmark = pytest.mark.unit


def _make_response(content: str = "", tool_calls: list = None) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=tool_calls or [])


# ---- agent 层 -----------------------------------------------------------------


def test_inject_rejected_when_window_closed():
    """窗口未打开 → 注入返回 None；deque 保持空。"""
    agent = SageAgent()
    assert agent.inject_user_message("补充指示") is None
    assert len(agent._pending_user_messages) == 0


def test_inject_returns_id_when_window_open():
    agent = SageAgent()
    agent.begin_accept_steer()
    msg_id = agent.inject_user_message("请改用方法 B")
    assert msg_id
    assert isinstance(msg_id, str)
    # deque 现在存 dict {id, text}
    pending = list(agent._pending_user_messages)
    assert len(pending) == 1
    assert pending[0] == {"id": msg_id, "text": "请改用方法 B"}


def test_inject_rejects_blank_content():
    agent = SageAgent()
    agent.begin_accept_steer()
    assert agent.inject_user_message("   ") is None


def test_cancel_user_message_removes_from_deque():
    agent = SageAgent()
    agent.begin_accept_steer()
    msg_id = agent.inject_user_message("待撤回")
    assert agent.cancel_user_message(msg_id) is True
    assert len(agent._pending_user_messages) == 0
    # 二次撤回返回 False（已不在队列）
    assert agent.cancel_user_message(msg_id) is False


def test_cancel_user_message_false_for_unknown_id():
    agent = SageAgent()
    agent.begin_accept_steer()
    agent.inject_user_message("别的")
    assert agent.cancel_user_message("not-an-id") is False
    # 原本那条还在
    assert len(list(agent._pending_user_messages)) == 1


def test_cancel_user_message_false_for_blank_id():
    agent = SageAgent()
    assert agent.cancel_user_message("") is False


@pytest.mark.asyncio()
async def test_steering_consumed_at_iteration_boundary():
    """run 中注入的消息在下一迭代边界以【用户补充】前缀进入 LLM 上下文，
    并推送 STEER_CONSUMED 事件携带 ids；deque 在边界后被清空。"""
    agent = SageAgent()
    agent.begin_accept_steer()
    agent.llm_client = MagicMock()
    tool_call = LLMToolCall(id="c1", name="list_dir", arguments="{}")
    calls = {"n": 0}

    async def _chat(messages, tools=None, tool_choice=None, retry_callback=None):
        calls["n"] += 1
        if calls["n"] == 1:
            # run 活跃窗口内注入 → 下一迭代边界（LLM 调用 2 之前）被消费
            agent.inject_user_message("改用方法 B")
            return _make_response(content="", tool_calls=[tool_call])
        return _make_response(content="done")

    agent.llm_client.chat = AsyncMock(side_effect=_chat)

    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(return_value=MagicMock(success=True, content={}, error=None))
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    messages = [{"role": "user", "content": "开始"}]
    events = []
    async for evt in agent.run_loop(messages, max_iterations=3):
        events.append(evt)

    assert AgentState.DONE in [e.state for e in events]
    # STEER_CONSUMED 事件推送并携带 ids
    consumed = [e for e in events if e.state == AgentState.STEER_CONSUMED]
    assert len(consumed) == 1
    ids = consumed[0].steer_info["ids"]
    assert len(ids) == 1
    # 注入后的 messages 列表里能找到【用户补充】前缀
    injected = [
        m for m in messages if m.get("role") == "user" and "改用方法 B" in str(m.get("content"))
    ]
    assert len(injected) == 1
    assert injected[0]["content"].startswith("【用户补充】")
    # 消费后 deque 被清空
    assert len(list(agent._pending_user_messages)) == 0


@pytest.mark.asyncio()
async def test_steer_window_narrows_after_run():
    """run 结束后注入拒绝；end_accept_steer 清空残留（不跨 run 泄漏）。"""
    agent = SageAgent()
    agent.begin_accept_steer()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(content="ok"))

    messages = [{"role": "user", "content": "hi"}]
    async for _ in agent.run_loop(messages):
        pass

    # run_loop finally 关闭注入窗口 + 清空队列
    assert agent._run_loop_active is False
    assert len(agent._pending_user_messages) == 0
    # 注入已拒绝
    assert agent.inject_user_message("晚了") is None
    assert not any("遗留" in str(m.get("content")) for m in messages)


@pytest.mark.asyncio()
async def test_end_accept_steer_clears_queue_before_run():
    """end_accept_steer（run 未启动即失败的路径）清空队列、拒绝新注入。"""
    agent = SageAgent()
    agent.begin_accept_steer()
    msg_id = agent.inject_user_message("缓存中的")
    assert msg_id is not None
    agent.end_accept_steer()
    assert len(list(agent._pending_user_messages)) == 0
    assert agent.inject_user_message("也拒绝") is None


# ---- 端点层 --------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_steer_endpoint_injects_into_registered_stream(monkeypatch):
    """端点返回 message_id，消息入队，队列形态为 dict {id, text}。"""
    from backend.api import legacy_routes as lr
    from backend.main import app

    agent = SageAgent()
    agent.begin_accept_steer()
    monkeypatch.setitem(lr._ACTIVE_STREAMS, "s1", {"agent": agent, "run_id": None})

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/chat/steer", json={"stream_id": "s1", "content": "用方法 B"}
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    msg_id = body["message_id"]
    assert msg_id
    assert isinstance(msg_id, str)

    pending = list(agent._pending_user_messages)
    assert len(pending) == 1
    assert pending[0] == {"id": msg_id, "text": "用方法 B"}


@pytest.mark.asyncio()
async def test_steer_endpoint_404_for_unknown_stream():
    from backend.main import app

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/chat/steer", json={"stream_id": "missing", "content": "hi"}
        )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "stream_not_found"


@pytest.mark.asyncio()
async def test_steer_endpoint_409_when_window_closed(monkeypatch):
    """窗口未打开 → 409 not_running（新契约：_accepts_steer 标志位，
    由 begin_accept_steer 打开）。"""
    from backend.api import legacy_routes as lr
    from backend.main import app

    agent = SageAgent()  # 未开注入窗口
    monkeypatch.setitem(lr._ACTIVE_STREAMS, "s2", {"agent": agent, "run_id": None})

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/chat/steer", json={"stream_id": "s2", "content": "hi"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "not_running"


@pytest.mark.asyncio()
async def test_steer_endpoint_400_for_blank_and_oversize(monkeypatch):
    from backend.api import legacy_routes as lr
    from backend.main import app

    agent = SageAgent()
    agent.begin_accept_steer()
    monkeypatch.setitem(lr._ACTIVE_STREAMS, "s3", {"agent": agent, "run_id": None})

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        blank = await client.post("/api/v1/chat/steer", json={"stream_id": "s3", "content": "   "})
        oversize = await client.post(
            "/api/v1/chat/steer", json={"stream_id": "s3", "content": "x" * 8193}
        )
    assert blank.status_code == 400
    assert blank.json()["detail"]["code"] == "empty_content"
    assert oversize.status_code == 400
    assert oversize.json()["detail"]["code"] == "msg_too_long"


@pytest.mark.asyncio()
async def test_steer_persists_on_consume_not_on_send(monkeypatch):
    """2026-11-07: 插话在被消费（drain）时才落库 —— 撤回的插话不留痕。

    端点返回后不应有任何 save 调用；等 run_loop 在迭代边界 drain 才写库。
    """
    from backend.api import legacy_routes as lr
    from backend.main import app

    saved = []

    class _Repo:
        def save(self, message):
            saved.append(message)
            return message

    agent = SageAgent()
    agent.begin_accept_steer()
    agent.message_repo = _Repo()
    monkeypatch.setitem(
        lr._ACTIVE_STREAMS, "s5", {"agent": agent, "run_id": None, "session_id": "sess-1"}
    )

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/chat/steer", json={"stream_id": "s5", "content": "第二段太长了"}
        )
    assert resp.status_code == 200
    # 发送时尚未落库
    assert len(saved) == 0

    # 现在 drain → 触发消费落库
    items = agent._drain_pending_user_messages()
    agent._persist_consumed_steers(items, "sess-1")
    assert len(saved) == 1
    row = saved[0]
    assert (row.role, row.session_id, row.subtype) == ("user", "sess-1", "steering")
    assert row.content == "第二段太长了"
    assert row.id == items[0]["id"]


@pytest.mark.asyncio()
async def test_steer_cancellation_leaves_no_trace(monkeypatch):
    """撤回的插话既不进 run 上下文、也不落库。"""
    from backend.api.chat_stream_state import _ACTIVE_STREAMS
    from backend.main import app

    saved = []

    class _Repo:
        def save(self, message):
            saved.append(message)
            return message

    agent = SageAgent()
    agent.begin_accept_steer()
    agent.message_repo = _Repo()
    monkeypatch.setitem(
        _ACTIVE_STREAMS, "s7", {"agent": agent, "run_id": None, "session_id": "sess-2"}
    )

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/chat/steer", json={"stream_id": "s7", "content": "待撤回"}
        )
    assert resp.status_code == 200
    msg_id = resp.json()["message_id"]

    # 撤回 —— removed=True（单独 client 避免 ASGI 生命周期关闭上一 client）
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cancel_resp = await client.post(
            "/api/v1/chat/steer/cancel",
            json={"stream_id": "s7", "message_id": msg_id},
        )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json() == {"removed": True}
    assert len(list(agent._pending_user_messages)) == 0

    # drain 时队列为空，落库也不触发
    items = agent._drain_pending_user_messages()
    agent._persist_consumed_steers(items, "sess-2")
    assert len(saved) == 0


@pytest.mark.asyncio()
async def test_steer_cancel_404_for_unknown_stream():
    from backend.main import app

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/chat/steer/cancel",
            json={"stream_id": "missing", "message_id": "whatever"},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio()
async def test_steer_cancel_returns_false_when_already_consumed(monkeypatch):
    """消费后再撤回：cancel 不报错，返回 removed=False。"""
    from backend.api import legacy_routes as lr
    from backend.main import app

    agent = SageAgent()
    agent.begin_accept_steer()
    msg_id = agent.inject_user_message("先被消费")
    assert msg_id is not None
    # 模拟消费：drain 清空
    agent._drain_pending_user_messages()
    monkeypatch.setitem(lr._ACTIVE_STREAMS, "s8", {"agent": agent, "run_id": None})

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/chat/steer/cancel",
            json={"stream_id": "s8", "message_id": msg_id},
        )
    assert resp.status_code == 200
    assert resp.json() == {"removed": False}


@pytest.mark.asyncio()
async def test_steering_injection_goes_through_ctx_budget_guard(monkeypatch):
    """P1: 插话必须经上下文预算复核。"""
    monkeypatch.setenv("SAGE_RUN_CTX_BUDGET_TOKENS", "900")

    agent = SageAgent()
    agent.begin_accept_steer()
    agent.llm_client = MagicMock()
    tool_call = LLMToolCall(id="c1", name="calculator", arguments="{}")
    calls = {"n": 0}

    async def _chat(messages, tools=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            agent.inject_user_message("B" * 2000)
            return _make_response(content="", tool_calls=[tool_call])
        return _make_response(content="done")

    agent.llm_client.chat = AsyncMock(side_effect=_chat)
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(return_value=MagicMock(success=True, content={}, error=None))
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    messages = [{"role": "user", "content": "A" * 2000}] + [
        {"role": "user", "content": f"filler {i}"} for i in range(4)
    ]
    async for _ in agent.run_loop(messages, max_iterations=3):
        pass

    assert calls["n"] == 2
    steered = [m for m in messages if str(m.get("content", "")).startswith("【用户补充】")]
    assert len(steered) == 1
    assert "[已压缩：早期内容]" in messages[0]["content"]


@pytest.mark.asyncio()
async def test_no_compaction_without_steering_at_same_budget(monkeypatch):
    monkeypatch.setenv("SAGE_RUN_CTX_BUDGET_TOKENS", "900")

    agent = SageAgent()
    agent.begin_accept_steer()
    agent.llm_client = MagicMock()
    tool_call = LLMToolCall(id="c1", name="calculator", arguments="{}")
    calls = {"n": 0}

    async def _chat(messages, tools=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _make_response(content="", tool_calls=[tool_call])
        return _make_response(content="done")

    agent.llm_client.chat = AsyncMock(side_effect=_chat)
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(return_value=MagicMock(success=True, content={}, error=None))
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    messages = [{"role": "user", "content": "A" * 2000}] + [
        {"role": "user", "content": f"filler {i}"} for i in range(4)
    ]
    async for _ in agent.run_loop(messages, max_iterations=3):
        pass

    assert messages[0]["content"] == "A" * 2000
