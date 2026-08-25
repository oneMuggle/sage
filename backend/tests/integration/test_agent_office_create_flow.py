"""office_create 审批链集成测试：写工作区外 → permission_request → 批准 → 生成。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.data.database import get_database
from backend.office.session_workspace import bind_session_workspace
from backend.services.permission_gate import init_permission_gate, reset_permission_gate
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _gate_lifecycle():
    reset_permission_gate()
    yield
    reset_permission_gate()


def _insert_session(conn, session_id: str) -> None:
    """bind_session_workspace 要求 sessions 表存在该行（_check_session_exists）。"""
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "office-create-flow", 1, 1),
    )
    conn.commit()


def _bind_workspace(session_id: str, workspace_in: Path) -> None:
    """注册会话 + 绑定到 workspace_in（office boundary 的来源）。"""
    conn = get_database().get_connection()
    _insert_session(conn, session_id)
    bind_session_workspace(conn, session_id, str(workspace_in))


def _office_agent(workspace_out: Path) -> SageAgent:
    """LLM 第一轮返回 office_create（写 workspace 外的目录），第二轮给终答。

    permission_enforcer 不注入 → 走 _build_permission_enforcer 默认装配，
    其 boundary validator 经 _office_boundary_resolver 从会话绑定解析。
    """
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call_office",
                        name="office_create",
                        arguments=(
                            '{"doc_type": "word", "output_dir": "%s", '  # noqa: UP031  # JSON 模板保留 % 占位
                            '"filename": "天气.docx", "content": {"title": "天气", '
                            '"paragraphs": [{"text": "今天天气很好"}]}}'
                            % str(workspace_out)
                        ),
                    )
                ],
            ),
            LLMResponse(content="已创建"),
        ]
    )
    return agent


def _tool_context(session_id: str, stream_id: str) -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id=session_id,
        stream_id=stream_id,
        binding_generation=1,
        office_doc_scope=frozenset(),
    )


async def test_office_create_outside_workspace_asks_then_creates(tmp_path):
    workspace_in = tmp_path / "ws-in"
    workspace_in.mkdir()
    workspace_out = tmp_path / "desktop"

    # 绑定会话到 workspace_in（office boundary 的来源）
    _bind_workspace("sess-office-1", workspace_in)
    token = set_tool_context(_tool_context("sess-office-1", "stream-1"))

    agent = _office_agent(workspace_out)
    gate = init_permission_gate()
    answered = {}

    async def approver():
        await asyncio.sleep(0.05)
        pending = gate.pending()
        assert len(pending) == 1
        answered["request"] = pending[0]
        assert pending[0].tool_name == "office_create"
        gate.answer(pending[0].request_id, approved=True)

    try:
        approver_task = asyncio.create_task(approver())
        events = []
        async for evt in agent.run_loop([{"role": "user", "content": "帮我建 word 到桌面"}]):
            events.append(evt)
        await approver_task
    finally:
        reset_tool_context(token)

    states = [e.state for e in events]
    assert AgentState.PERMISSION_REQUEST in states
    assert events[-1].state == AgentState.DONE
    # T7.5 起,binding-aware 委托把 office_create 路由到 OfficeToolService.create,
    # 文件落地 ``<binding.workspace>/office/<doc_type>/<doc_id>/`` 而非
    # LLM 提供的 output_dir;权限请求触发点在 M1 path_boundary_validator,因为
    # LLM 声称要写的是 workspace_in(已绑定)之外的目录。这里通过数据库注册断言
    # 证明审批通过后 doc 真的被登记(从而保证 office_list/read 能看到)。
    from backend.office.storage import list_documents

    conn = get_database().get_connection()
    registered = list_documents(conn, str(workspace_in))
    assert any(doc.generated_filename == "天气.docx" for doc in registered), (
        f"OfficeToolService.create 未注册文档到 workspace_in: {registered}"
    )


async def test_office_create_denial_does_not_create(tmp_path):
    workspace_in = tmp_path / "ws-in"
    workspace_in.mkdir()
    workspace_out = tmp_path / "desktop"

    _bind_workspace("sess-office-2", workspace_in)
    token = set_tool_context(_tool_context("sess-office-2", "stream-2"))

    agent = _office_agent(workspace_out)
    gate = init_permission_gate()

    async def denier():
        await asyncio.sleep(0.05)
        pending = gate.pending()
        gate.answer(pending[0].request_id, approved=False)

    try:
        denier_task = asyncio.create_task(denier())
        events = []
        async for evt in agent.run_loop([{"role": "user", "content": "帮我建 word 到桌面"}]):
            events.append(evt)
        await denier_task
    finally:
        reset_tool_context(token)

    assert not (workspace_out / "天气.docx").exists()
    observing = next(e for e in events if e.state == AgentState.OBSERVING)
    assert observing.tool_result.is_error is True
    assert "未获批准" in observing.tool_result.content
