"""2026-07-30: 验证 chat 端点正确透传 agent_id。

背景：之前 chat 端点全部用 ``SageAgent()`` 不传 agent_id，导致 profile 永远
是 None → allowed_tools 是 None → 所有工具暴露 → memory_manager 的窄权限 agent
拿到 list_dir/read_file → 真实工作流被截断为 max_iterations_exceeded。

本测试覆盖：
1. ChatRequest schema 接受 agent_id 字段 (Optional, 默认 None)
2. /chat 在不传 agent_id 时 fallback 到 "primary"
3. /chat 在传 agent_id="coder" 时直接透传
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app

CHAT_PATH = "/api/v1/chat"

# 默认 hex 模式下 /chat 已被 hex_routes 接管，本文件专门测 legacy 行为
_API_MODE = os.environ.get("API_MODE", "legacy").lower()
_LEGACY_ONLY = pytest.mark.skipif(
    _API_MODE != "legacy",
    reason=f"本文件测 legacy /chat 行为；当前 API_MODE={_API_MODE!r}（需 legacy）",
)


# ---------- Schema ----------


def test_chat_request_schema_accepts_agent_id():
    """ChatRequest 应接受 agent_id 字段，向后兼容（不传也 OK）。"""
    from backend.api.legacy_routes import ChatRequest

    req = ChatRequest(session_id="abc", message="hi")
    assert req.agent_id is None

    req = ChatRequest(session_id="abc", message="hi", agent_id="coder")
    assert req.agent_id == "coder"


# ---------- /chat endpoint: agent_id 透传 ----------
#
# 测试策略：让 mock 的 chat() 抛 LLMError 让端点走 error 早退路径,
# 避免构造完整 MessageResponse。关键是断言 SageAgent 被以正确 kwargs 调用。


@pytest.mark.asyncio()
@_LEGACY_ONLY
async def test_chat_defaults_to_primary_agent_when_agent_id_omitted():
    """不传 agent_id 时，/chat 应 fallback 到 "primary"。

    这是修复 chat 端点不加载 profile 的核心契约 —— 默认行为变化必须可见。
    """
    from backend.core.errors import LLMError, LLMErrorType

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        mock_agent_instance = MockAgent.return_value
        mock_agent_instance.chat = AsyncMock(
            side_effect=LLMError(LLMErrorType.AUTH_FAILED, "auth fail")
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                CHAT_PATH,
                json={
                    "session_id": "00000000-0000-0000-0000-000000000000",
                    "message": "hi",
                },
            )
        assert resp.status_code == 200  # LLMError → HTTP 200 + error 字段
        MockAgent.assert_called_once()
        call_kwargs = MockAgent.call_args.kwargs
        assert call_kwargs.get("agent_id") == "primary", (
            f"expected agent_id='primary' fallback, got {call_kwargs.get('agent_id')!r}"
        )


@pytest.mark.asyncio()
@_LEGACY_ONLY
async def test_chat_passes_explicit_agent_id():
    """显式传 agent_id="coder" 时,应直接透传,不要覆盖。"""
    from backend.core.errors import LLMError, LLMErrorType

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        mock_agent_instance = MockAgent.return_value
        mock_agent_instance.chat = AsyncMock(
            side_effect=LLMError(LLMErrorType.AUTH_FAILED, "auth fail")
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                CHAT_PATH,
                json={
                    "session_id": "00000000-0000-0000-0000-000000000000",
                    "message": "review this code",
                    "agent_id": "coder",
                },
            )
        assert resp.status_code == 200
        call_kwargs = MockAgent.call_args.kwargs
        assert call_kwargs.get("agent_id") == "coder"


@pytest.mark.asyncio()
@_LEGACY_ONLY
async def test_chat_treats_empty_string_agent_id_as_primary():
    """空字符串 agent_id 应 fallback 到 primary(等价 None)。"""
    from backend.core.errors import LLMError, LLMErrorType

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        mock_agent_instance = MockAgent.return_value
        mock_agent_instance.chat = AsyncMock(
            side_effect=LLMError(LLMErrorType.AUTH_FAILED, "auth fail")
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                CHAT_PATH,
                json={
                    "session_id": "00000000-0000-0000-0000-000000000000",
                    "message": "hi",
                    "agent_id": "",
                },
            )
        assert resp.status_code == 200
        call_kwargs = MockAgent.call_args.kwargs
        assert call_kwargs.get("agent_id") == "primary"