"""
/chat/stream 端点 NDJSON 流式响应测试

验证 /api/v1/chat/stream 端点：
1. 以 NDJSON 格式逐事件下发 AgentEvent
2. 每个事件可被独立解析为 JSON 对象
3. thinking / acting / observing / done 状态正确序列化
4. tool_call 字段包含 OpenAI 风格的 function.name 结构

注意：路由通过 app.include_router(api_router, prefix="/api/v1") 注册，
所以实际挂载路径是 /api/v1/chat/stream。
"""
import json
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.core.agent_state import AgentEvent, AgentState, ToolCallRequest, ToolCallResult
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"


@pytest.mark.asyncio()
async def test_chat_stream_yields_ndjson_events():
    """/chat/stream 端点以 NDJSON 格式返回 AgentEvent。"""
    async def mock_run_loop(messages, max_iterations=5):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.ACTING,
            iteration=0,
            tool_call=ToolCallRequest(
                id="c1",
                name="calculator",
                arguments={"expression": "1+1"},
            ),
        )
        yield AgentEvent(
            state=AgentState.OBSERVING,
            iteration=0,
            tool_result=ToolCallResult(tool_call_id="c1", content="2"),
        )
        yield AgentEvent(
            state=AgentState.DONE,
            iteration=1,
            content="答案是 2",
        )

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        mock_agent = MockAgent.return_value
        mock_agent.run_loop = mock_run_loop

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(CHAT_STREAM_PATH, json={
                "session_id": "00000000-0000-0000-0000-000000000000",
                "message": "1+1 等于几",
            })

        assert resp.status_code == 200
        lines = [line for line in resp.text.split("\n") if line.strip()]
        events = [json.loads(line) for line in lines]
        assert len(events) == 4
        assert events[0]["state"] == "thinking"
        assert events[1]["state"] == "acting"
        assert events[1]["tool_call"]["function"]["name"] == "calculator"
        assert events[2]["state"] == "observing"
        assert events[3]["state"] == "done"
        assert events[3]["content"] == "答案是 2"
