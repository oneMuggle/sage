"""RT5 (round7) — 单 agent steering 测试。

覆盖两层：
- agent 层：inject_user_message 的运行窗口语义 + run_loop 迭代边界消费
  + 迭代边界上下文预算复核（插话计入高水位，反证对照）
- 端点层：POST /api/v1/chat/steer 的 200/404/409/400 面 + 插话落库
  （写入 ``subtype='steering'`` 行；落库失败不回滚已生效的注入）
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


def test_inject_rejected_when_run_not_active():
    agent = SageAgent()
    assert agent.inject_user_message("补充指示") is False
    assert len(agent._pending_user_messages) == 0


def test_inject_rejects_blank_content():
    agent = SageAgent()
    agent._run_loop_active = True
    assert agent.inject_user_message("   ") is False


@pytest.mark.asyncio()
async def test_steering_consumed_at_iteration_boundary():
    """run 中注入的消息在下一迭代边界以【用户补充】前缀进入 LLM 上下文。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    tool_call = LLMToolCall(id="c1", name="calculator", arguments="{}")
    calls = {"n": 0}

    async def _chat(messages, tools=None):
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
    injected = [
        m for m in messages if m.get("role") == "user" and "改用方法 B" in str(m.get("content"))
    ]
    assert len(injected) == 1
    assert injected[0]["content"].startswith("【用户补充】")


@pytest.mark.asyncio()
async def test_steer_window_narrows_after_run():
    """run 结束后 inject 拒绝；run 启动时清空残留（不跨 run 泄漏）。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(content="ok"))

    agent._pending_user_messages.append("上一 run 的遗留")
    messages = [{"role": "user", "content": "hi"}]
    async for _ in agent.run_loop(messages):
        pass

    assert agent._run_loop_active is False
    assert len(agent._pending_user_messages) == 0
    assert agent.inject_user_message("晚了") is False
    assert not any("遗留" in str(m.get("content")) for m in messages)


# ---- 端点层 --------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_steer_endpoint_injects_into_registered_stream(monkeypatch):
    from backend.api import legacy_routes as lr
    from backend.main import app

    agent = SageAgent()
    agent._run_loop_active = True
    monkeypatch.setitem(lr._ACTIVE_STREAMS, "s1", {"agent": agent, "run_id": None})

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/chat/steer", json={"stream_id": "s1", "content": "用方法 B"}
        )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert list(agent._pending_user_messages) == ["用方法 B"]
    assert agent.inject_user_message("校验入队") is True  # 窗口仍开着
    assert len(agent._pending_user_messages) == 2


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
async def test_steer_endpoint_409_when_not_running(monkeypatch):
    from backend.api import legacy_routes as lr
    from backend.main import app

    agent = SageAgent()  # 未在 run 窗口
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
    agent._run_loop_active = True
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
async def test_steer_endpoint_persists_steering_row(monkeypatch):
    """插话必须落库 —— run 内注入只活在 agent 内存的 messages 列表，不落库
    则下一轮从 DB 装配历史时这条更正凭空消失（前端气泡也会被对账抹掉）。"""
    from backend.api import legacy_routes as lr
    from backend.main import app

    saved = []

    class _Repo:
        def save(self, message):
            saved.append(message)
            return message

    monkeypatch.setattr(lr, "MessageRepository", _Repo)
    agent = SageAgent()
    agent._run_loop_active = True
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
    assert len(saved) == 1
    row = saved[0]
    assert (row.role, row.session_id, row.subtype) == ("user", "sess-1", "steering")
    # 原文入库；【用户补充】前缀只是 run 内注入时的措辞，不该进历史
    assert row.content == "第二段太长了"


@pytest.mark.asyncio()
async def test_steer_endpoint_survives_persistence_failure(monkeypatch):
    """落库失败不回滚已生效的注入：插话已在当前 run 排队，端点仍返回 200。"""
    from backend.api import legacy_routes as lr
    from backend.main import app

    class _BrokenRepo:
        def save(self, message):
            raise RuntimeError("db is locked")

    monkeypatch.setattr(lr, "MessageRepository", _BrokenRepo)
    agent = SageAgent()
    agent._run_loop_active = True
    monkeypatch.setitem(
        lr._ACTIVE_STREAMS, "s6", {"agent": agent, "run_id": None, "session_id": "sess-1"}
    )

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/chat/steer", json={"stream_id": "s6", "content": "照样生效"}
        )

    assert resp.status_code == 200
    assert list(agent._pending_user_messages) == ["照样生效"]


@pytest.mark.asyncio()
async def test_steering_injection_goes_through_ctx_budget_guard(monkeypatch):
    """P1: 插话必须经上下文预算复核。

    run_loop 迭代边界的契约顺序是 drain → estimate → compact → LLM 调用。
    若预算检查发生在注入之前，插话内容就绕过了高水位治理：本次请求照样
    按"注入后"的体积发给模型，却没人据此做过压缩。
    """
    # 预算 900：注入前 ~500 token（不触发），加上 2000 字符的插话后越线
    monkeypatch.setenv("SAGE_RUN_CTX_BUDGET_TOKENS", "900")

    agent = SageAgent()
    agent.llm_client = MagicMock()
    tool_call = LLMToolCall(id="c1", name="calculator", arguments="{}")
    calls = {"n": 0}

    async def _chat(messages, tools=None):
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
    # 插话进了上下文（run 收尾还会追加终稿 assistant 行，故按内容找）
    steered = [m for m in messages if str(m.get("content", "")).startswith("【用户补充】")]
    assert len(steered) == 1
    # 并且正是因为插话越线，早期长内容才被就地压缩
    assert "[已压缩：早期内容]" in messages[0]["content"]


@pytest.mark.asyncio()
async def test_no_compaction_without_steering_at_same_budget(monkeypatch):
    """上一条的反证：同样的历史、同样的 900 预算，不插话就不会越线压缩。

    没有这条对照，上一条测试可能只是"早期内容本来就该被压"，证明不了
    插话参与了预算复核。
    """
    monkeypatch.setenv("SAGE_RUN_CTX_BUDGET_TOKENS", "900")

    agent = SageAgent()
    agent.llm_client = MagicMock()
    tool_call = LLMToolCall(id="c1", name="calculator", arguments="{}")
    calls = {"n": 0}

    async def _chat(messages, tools=None):
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
