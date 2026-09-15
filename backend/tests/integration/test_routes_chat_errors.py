"""
/chat 端点结构化错误响应测试

验证 /chat 端点：
1. LLMError 时返回 HTTP 200 + 结构化 error 字段（而非 500）
2. 错误字段包含 type/message/status_code/retry_after
3. 响应头包含 x-request-id 用于诊断追踪

注意：路由通过 app.include_router(api_router, prefix="/api/v1") 注册，
所以实际挂载路径是 /api/v1/chat 而非 /chat。

P2 双轨说明：本文件测试的是**legacy** /chat 行为（通过 SageAgent 直调）。
在 API_MODE=hex 下，``/chat`` 路由由 ``hex_routes`` 提供（走 ChatService），
本文件不适用——对应测试在 ``test_hex_routes_chat.py``。
"""

import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.core.errors import LLMError, LLMErrorType
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_PATH = "/api/v1/chat"

# 默认 hex 模式下 /chat 已被 hex_routes 接管，本文件专门测 legacy 行为
# PG-A1: local default 同步 main.py flip (hex→legacy)
_API_MODE = os.environ.get("API_MODE", "legacy").lower()
_LEGACY_ONLY = pytest.mark.skipif(
    _API_MODE != "legacy",
    reason=f"本文件测 legacy /chat 行为；当前 API_MODE={_API_MODE!r}（需 legacy）",
)


@pytest.mark.asyncio()
@_LEGACY_ONLY
async def test_chat_returns_structured_error_on_auth_failed():
    """LLM 401 时 /chat 返回结构化错误响应（HTTP 200 + error 字段）。"""
    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        mock_agent_instance = MockAgent.return_value
        mock_agent_instance.chat = AsyncMock(
            side_effect=LLMError(LLMErrorType.AUTH_FAILED, "API Key 无效", status_code=401)
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                CHAT_PATH,
                json={
                    "session_id": "00000000-0000-0000-0000-000000000000",
                    "message": "hi",
                    "api_key": "bad-key",
                    "api_url": "https://api.example.com/v1",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["type"] == "auth_failed"
        assert body["error"]["message"] == "API Key 无效"
        assert body["message"] is None


@pytest.mark.asyncio()
@_LEGACY_ONLY
async def test_chat_returns_structured_error_on_timeout():
    """LLM 超时时 /chat 返回 timeout 错误。"""
    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        mock_agent_instance = MockAgent.return_value
        mock_agent_instance.chat = AsyncMock(
            side_effect=LLMError(LLMErrorType.TIMEOUT, "请求 LLM 超时")
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                CHAT_PATH,
                json={
                    "session_id": "00000000-0000-0000-0000-000000000000",
                    "message": "hi",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["type"] == "timeout"


@pytest.mark.asyncio()
@_LEGACY_ONLY
async def test_chat_handles_agent_returning_error_dict_without_crashing():
    """回归测试：agent.chat() 返回 error 字典时（Task 6 后的新契约），
    路由不能因 success 日志崩溃，要透传 error 字典给前端。
    这是用户报告的'发送消息无响应' bug 的根因。"""
    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        mock_agent_instance = MockAgent.return_value
        # chat() 返回 error 字典而不是 raise LLMError（Task 6 的新契约）
        mock_agent_instance.chat = AsyncMock(
            return_value={
                "error": {
                    "type": "auth_failed",
                    "message": "API Key 无效",
                    "status_code": 401,
                    "retry_after": None,
                },
                "message": None,
                "session": None,
            }
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                CHAT_PATH,
                json={
                    "session_id": "00000000-0000-0000-0000-000000000000",
                    "message": "hi",
                    "api_key": "bad-key",
                    "api_url": "https://api.example.com/v1",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["type"] == "auth_failed"
        assert body["error"]["message"] == "API Key 无效"
        assert body["message"] is None


@pytest.mark.asyncio()
@_LEGACY_ONLY
async def test_chat_request_id_in_response_header():
    """响应头应包含 x-request-id 用于诊断追踪。"""
    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        mock_agent_instance = MockAgent.return_value
        mock_agent_instance.chat = AsyncMock(
            return_value={
                "message": {
                    "id": "m1",
                    "session_id": "00000000-0000-0000-0000-000000000000",
                    "role": "assistant",
                    "content": "ok",
                    "created_at": 0,
                },
                "session": None,
            }
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                CHAT_PATH,
                json={
                    "session_id": "00000000-0000-0000-0000-000000000000",
                    "message": "hi",
                },
            )
        assert "x-request-id" in resp.headers


@pytest.mark.asyncio()
@_LEGACY_ONLY
async def test_chat_response_header_request_id_matches_handler_logs(caplog):
    """响应头 x-request-id 应与 handler 日志中的 [REQ xxx] 一致。"""
    import logging

    caplog.set_level(logging.INFO, logger="backend.api.legacy_routes")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        mock_agent_instance = MockAgent.return_value
        mock_agent_instance.chat = AsyncMock(
            return_value={
                "message": {
                    "id": "m1",
                    "session_id": "00000000-0000-0000-0000-000000000000",
                    "role": "assistant",
                    "content": "ok",
                    "created_at": 0,
                },
                "session": None,
            }
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                CHAT_PATH,
                json={
                    "session_id": "00000000-0000-0000-0000-000000000000",
                    "message": "hi",
                },
            )

        header_id = resp.headers.get("x-request-id")
        assert header_id is not None

        # Verify the same ID appears in at least one log record
        log_text = caplog.text
        assert (
            f"[REQ {header_id}]" in log_text
        ), f"Expected log to contain [REQ {header_id}], got:\n{log_text}"
