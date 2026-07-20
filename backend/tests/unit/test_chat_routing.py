"""
Chat 路由分流测试（阶段 2）

验证:
1. _should_use_orchestrator(message) 分流函数
2. AgentOrchestrator._execute_agent_task 调用真实 SageAgent.run_loop
3. /chat 和 /chat/stream 路由分流逻辑
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

_API_MODE = os.environ.get("API_MODE", "legacy").lower()
_LEGACY_ONLY = pytest.mark.skipif(
    _API_MODE == "hex",
    reason=(
        "本文件测 legacy_routes /chat 的 SageAgent/AgentOrchestrator 分流逻辑；"
        f"当前 API_MODE={_API_MODE!r}（hex 模式下 /chat 路由由 hex_routes 接管，"
        "本测试的 legacy 路径不可达）"
    ),
)


# =============================================================================
# Hex DI override（autouse）
# =============================================================================
#
# P4 fix-forward: hex 模式下 main.py lifespan 会装配 get_chat_service override,
# 但 conftest.setup_test_db 把 _db 替换为 tmp db, 可能导致 lifespan 启动时部分
# 服务(Planner / Heartbeat / Scheduler)早退, 使得 get_chat_service override
# 实际上不会落到 app.dependency_overrides 上。本 fixture 显式 mock
# ChatService(7 个 port: llm/tools/skills/storage/metrics/events/memory),
# 保证 unit/integration test 中 hex_routes /chat 端点不会被
# NotImplementedError 阻断。
#
# 与 tests/integration/test_settings_endpoint.py 的 _hex_di_override 模式对齐。
@pytest.fixture(autouse=True)
def _hex_di_override_chat_service():
    """hex 模式 /chat 路由注入 mock ChatService,避免 NotImplementedError。"""
    from sage_core import Message, Role

    from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
    from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
    from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
    from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
    from backend.api.hex_routes import get_chat_service
    from backend.application.services.chat_service import ChatService
    from backend.main import app

    mock_tool = MagicMock()
    mock_tool.execute.return_value = MagicMock(success=True, output="ok", error=None)
    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    mock_registry.get.return_value = mock_tool

    fake_svc = ChatService(
        llm=MockLLMAdapter(responses=[Message(role=Role.ASSISTANT, content="ok")]),
        tools=InprocToolAdapter(registry=mock_registry),
        skills=MagicMock(),
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=MagicMock(),  # emit 接受任意 dict
    )
    saved_override = app.dependency_overrides.get(get_chat_service)
    app.dependency_overrides[get_chat_service] = lambda: fake_svc
    yield
    if saved_override is not None:
        app.dependency_overrides[get_chat_service] = saved_override
    else:
        app.dependency_overrides.pop(get_chat_service, None)


# =============================================================================
# _should_use_orchestrator 分流函数
# =============================================================================


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("对比一下 React 和 Vue", True),
        ("比较这两种方案", True),
        ("总结这篇文章并给出建议", True),
        ("先搜索相关资料，然后分析", True),
        ("接着做下一步", True),
        ("分析这段代码", True),
        ("multi-step task", True),
        ("你好", False),
        ("今天天气怎么样", False),
        ("帮我写一个函数", False),  # 单步任务
    ],
)
def test_should_use_orchestrator_keyword_matching(message: str, expected: bool):
    """关键词匹配应正确分流。"""
    from backend.api.legacy_routes import _should_use_orchestrator

    assert _should_use_orchestrator(message) == expected


def test_should_use_orchestrator_long_message():
    """消息长度 > 200 字应走 orchestrator。"""
    from backend.api.legacy_routes import _should_use_orchestrator

    long_message = "帮我分析这个问题。" + "这是一个非常复杂的问题，涉及多个方面。" * 20
    assert len(long_message) > 200
    assert _should_use_orchestrator(long_message) is True


def test_should_use_orchestrator_short_message():
    """短消息不走 orchestrator。"""
    from backend.api.legacy_routes import _should_use_orchestrator

    short_message = "你好"
    assert len(short_message) < 200
    assert _should_use_orchestrator(short_message) is False


# =============================================================================
# AgentOrchestrator._execute_agent_task 调用真实 SageAgent
# =============================================================================


@pytest.mark.asyncio()
async def test_orchestrator_execute_agent_task_calls_sage_agent_run_loop():
    """_execute_agent_task 应调用 SageAgent.run_loop（而非直接调 LLM）。"""
    from backend.core.legacy.agent_state import AgentEvent, AgentState
    from backend.core.legacy.orchestrator import AgentOrchestrator

    orchestrator = AgentOrchestrator()

    async def mock_event_gen():
        yield AgentEvent(state=AgentState.THINKING, iteration=0, agent_id="primary")
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="你好！", agent_id="primary")

    mock_run_loop = MagicMock(return_value=mock_event_gen())

    with patch("backend.core.legacy.agent.SageAgent") as MockSageAgent:
        mock_agent_instance = MagicMock()
        mock_agent_instance.run_loop = mock_run_loop
        MockSageAgent.return_value = mock_agent_instance

        result = await orchestrator._execute_agent_task(
            session_id="test-session",
            agent_id="primary",
            message="你好",
            history=None,
        )

        # 验证 SageAgent 被实例化（带 agent_id + llm_config=None）
        MockSageAgent.assert_called_once_with(agent_id="primary", llm_config=None)

        # 验证 run_loop 被调用
        assert mock_run_loop.called

        # 验证返回结果包含 response
        assert "response" in result


# =============================================================================
# /chat 路由分流（集成测试）
# =============================================================================


@_LEGACY_ONLY
def test_chat_route_uses_single_agent_for_simple_message():
    """简单消息应走单 agent 路径（不走 orchestrator）。"""
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
            json={"session_id": "sess-1", "message": "你好"},
        )

        assert response.status_code == 200
        assert mock_agent.chat.called


@_LEGACY_ONLY
def test_chat_route_uses_orchestrator_for_complex_message():
    """复杂消息应走 orchestrator 路径。"""
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as client, patch(
        "backend.core.legacy.orchestrator.AgentOrchestrator"
    ) as MockOrchestrator:
        mock_orch = MagicMock()
        mock_orch.process_request = AsyncMock(
            return_value={
                "message": {
                    "id": "msg-1",
                    "session_id": "sess-1",
                    "role": "assistant",
                    "content": "对比结果...",
                    "created_at": 1234567890,
                },
                "session": {"id": "sess-1", "title": "Test"},
                "metadata": {"intent": "multi_step", "agent_used": "multi_step"},
            }
        )
        MockOrchestrator.return_value = mock_orch

        response = client.post(
            "/api/v1/chat",
            json={"session_id": "sess-1", "message": "对比一下 React 和 Vue"},
        )

        assert response.status_code == 200
        assert mock_orch.process_request.called
