"""
Chat 路由测试

验证:
1. /chat 恒走单 SageAgent（legacy 启发式 AgentOrchestrator 已下线，
   多 agent 编排统一由 ChatDispatcher / /chat/stream 承担）
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# =============================================================================
# /chat 路由（恒走单 agent）
# =============================================================================


def test_chat_route_uses_single_agent():
    """/chat 应恒走单 agent 路径（无启发式分流）。"""
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as client, patch("backend.api.legacy_routes.SageAgent") as MockSageAgent:
        mock_agent = MagicMock()
        mock_agent.chat = AsyncMock(
            return_value={
                "message": {
                    "id": "msg-1",
                    "session_id": "sess-1",
                    "role": "assistant",
                    "content": "你好！",
                    "created_at": 1234567890,
                },
                "session": {"id": "sess-1", "title": "Test"},
            }
        )
        MockSageAgent.return_value = mock_agent

        response = client.post(
            "/api/v1/chat",
            json={"session_id": "sess-1", "message": "对比一下 React 和 Vue"},
        )

        assert response.status_code == 200
        assert mock_agent.chat.called
