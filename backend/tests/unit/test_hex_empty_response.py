"""hex 路径空响应守卫测试（Round 14）"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.application.services.chat_service import ChatService
from backend.domain.message import Message, Role

pytestmark = pytest.mark.unit


def _make_service(side_effects):
    mock_llm = AsyncMock()
    mock_llm.chat = AsyncMock(side_effect=side_effects)
    service = ChatService(
        llm=mock_llm,
        tools=MagicMock(),
        skills=MagicMock(),
        storage=AsyncMock(),
        metrics=MagicMock(),
        events=MagicMock(),
    )
    service.storage.get_messages.return_value = []
    service.tools.list_tools.return_value = []
    return service, mock_llm


class TestRetryEmptyResponse:
    @pytest.mark.asyncio()
    async def test_empty_then_valid_returns_valid(self):
        """空响应 → 注入提示重试 → 返回非空响应"""
        service, llm = _make_service(
            [Message(role=Role.ASSISTANT, content="这是有效回复")]
        )
        history = [Message(role=Role.USER, content="hi")]
        result = await service._retry_empty_response(history, None)
        assert result is not None
        assert result.content == "这是有效回复"
        # 重试请求带了 system 提示
        args = llm.chat.call_args
        messages = args.kwargs.get("messages") or args.args[0]
        assert any(
            m.role == Role.SYSTEM and "响应内容为空" in (m.content or "")
            for m in messages
        )

    @pytest.mark.asyncio()
    async def test_always_empty_returns_none(self):
        """始终空 → None（调用方保留原响应）"""
        service, _ = _make_service(
            [
                Message(role=Role.ASSISTANT, content=""),
                Message(role=Role.ASSISTANT, content="  "),
            ]
        )
        result = await service._retry_empty_response(
            [Message(role=Role.USER, content="hi")], None
        )
        assert result is None

    @pytest.mark.asyncio()
    async def test_llm_failure_returns_none(self):
        service, _ = _make_service([RuntimeError("down")])
        result = await service._retry_empty_response(
            [Message(role=Role.USER, content="hi")], None
        )
        assert result is None


class TestRunTurnGuardIntegration:
    @pytest.mark.asyncio()
    async def test_run_turn_retries_empty_response(self):
        """run_turn 空响应 → 自动重试并持久化非空回复"""
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(
            side_effect=[
                Message(role=Role.ASSISTANT, content=""),
                Message(role=Role.ASSISTANT, content="重试后的回复"),
            ]
        )
        service = ChatService(
            llm=mock_llm,
            tools=MagicMock(),
            skills=MagicMock(),
            storage=AsyncMock(),
            metrics=MagicMock(),
            events=MagicMock(),
        )
        service.storage.get_messages.return_value = []
        service.tools.list_tools.return_value = []

        messages = await service._run_turn_inner(
            session_id="sess-guard",
            user_message=Message(role=Role.USER, content="hi"),
            span=MagicMock(),
        )
        assert mock_llm.chat.call_count == 2
        assistant = [m for m in messages if m.role == Role.ASSISTANT]
        assert assistant
        assert assistant[-1].content == "重试后的回复"
