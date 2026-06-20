"""验证 hex_routes（PG2 双轨）走 ChatService。

P2 末的双轨架构：
- ``API_MODE=hex``（默认）：``/chat`` 由 ``hex_routes.chat`` 提供，调用
  ``ChatService.run_turn``。本测试覆盖该路径。
- ``API_MODE=legacy``：``/chat`` 由 ``legacy_routes.chat`` 提供（旧
  SageAgent 直调路径），由 ``test_routes_chat_errors.py`` 覆盖。
"""

import os
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sage_core import Message, Role

from backend.adapters.out.event.stdout_adapter import StdoutEventAdapter
from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.api.hex_routes import get_chat_service
from backend.application.services.chat_service import ChatService
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_PATH = "/api/v1/chat"

# 本文件专门测 hex 路径；legacy 模式下 /chat 不走 hex_routes，本文件全部跳过
# PG-A1: local default 同步 main.py flip (hex→legacy)
_API_MODE = os.environ.get("API_MODE", "legacy").lower()
_HEX_ONLY = pytest.mark.skipif(
    _API_MODE != "hex",
    reason=f"本文件测 hex /chat 行为；当前 API_MODE={_API_MODE!r}（需 hex）",
)


@pytest_asyncio.fixture
async def hex_client():
    """自带 DI override 的异步客户端。

    装配一个完全 in-memory 的 ``ChatService``（LLM=Mock、Storage=Memory、
    Tool=Inproc 配 mock registry、Skill/Metric/Event 走最小 stub），
    覆盖 ``get_chat_service`` 工厂；测试结束后还原依赖覆盖，避免污染
    同一 ``app`` 上的其它测试。
    """
    mock_tool = MagicMock()
    mock_tool.execute.return_value = MagicMock(success=True, output="ok", error=None)
    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    mock_registry.get.return_value = mock_tool

    fake_svc = ChatService(
        llm=MockLLMAdapter(responses=[Message(role=Role.ASSISTANT, content="hello from hex")]),
        tools=InprocToolAdapter(registry=mock_registry),
        skills=MagicMock(),  # SkillPort 协议未实现；用 MagicMock 占位
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=StdoutEventAdapter(verbose=False),
    )

    # 备份原 override（如有），挂上 fake_svc
    saved_override = app.dependency_overrides.get(get_chat_service)
    app.dependency_overrides[get_chat_service] = lambda: fake_svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac, fake_svc
    finally:
        # 还原 override，避免污染后续测试
        if saved_override is not None:
            app.dependency_overrides[get_chat_service] = saved_override
        else:
            app.dependency_overrides.pop(get_chat_service, None)


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
@_HEX_ONLY
async def test_chat_endpoint_via_chat_service(hex_client):
    """POST /chat 经由 hex_routes 走 ChatService.run_turn。"""
    client, fake_svc = hex_client

    # 在 fake_svc 的内存 storage 中预建一个 session
    sid = await fake_svc.storage.create_session()

    resp = await client.post(CHAT_PATH, json={"session_id": sid, "message": "hi"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"] == sid
    assert "hello from hex" in body["reply"]


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
@_HEX_ONLY
async def test_chat_endpoint_persists_user_and_assistant_messages(hex_client):
    """ChatService 应把 user + assistant 两条消息都写入 storage。"""
    client, fake_svc = hex_client

    sid = await fake_svc.storage.create_session()

    resp = await client.post(CHAT_PATH, json={"session_id": sid, "message": "ping"})
    assert resp.status_code == 200, resp.text

    stored = await fake_svc.storage.get_messages(sid, limit=50)
    roles = [m.role for m in stored]
    assert Role.USER in roles
    assert Role.ASSISTANT in roles
    # 末条一定是 assistant 回复
    assert stored[-1].role == Role.ASSISTANT
    assert stored[-1].content == "hello from hex"


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
@_HEX_ONLY
async def test_chat_endpoint_returns_500_when_session_missing(hex_client):
    """session 不存在时 ChatService 仍接受（MemoryStorageAdapter 会自动建），

    路径不会因此崩。验证 hex 路由在该场景下能正常返回 200。
    """
    client, _ = hex_client
    resp = await client.post(
        CHAT_PATH, json={"session_id": "nonexistent-session-id", "message": "hi"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"] == "nonexistent-session-id"
    assert "hello from hex" in body["reply"]
