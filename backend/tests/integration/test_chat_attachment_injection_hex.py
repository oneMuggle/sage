"""/chat 集成测试 (hex 路径): Office 附件摘要注入 LLM system messages。

Hex /chat 走 ChatService.run_turn, 而 run_turn 内部调用 MockLLMAdapter.chat().
本测试通过 MockLLMAdapter.calls 捕获 LLM 实际收到的 messages, 校验附件块
已作为 system message 注入 system_content + history 链中。

与 legacy /chat/stream 平行, 但 mock 点不同:
- legacy: patch backend.api.legacy_routes.SageAgent.run_loop
- hex: 检查 svc.llm (MockLLMAdapter) 的 calls 属性
"""

from __future__ import annotations

import os
from typing import Any, List
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
from backend.chat import attachment_resolver
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_PATH = "/api/v1/chat"

# 本文件专门测 hex 路径;legacy 模式下 /chat 不走 hex_routes, 本文件全部跳过
_API_MODE = os.environ.get("API_MODE", "legacy").lower()
_HEX_ONLY = pytest.mark.skipif(
    _API_MODE != "hex",
    reason=f"本文件测 hex /chat 行为;当前 API_MODE={_API_MODE!r}(需 hex)",
)

ATTACHMENT_PROMPT_PREFIX = (
    "The user has referenced the following attached documents. "
    "Treat them as primary context for the user's request.\n\n"
)


@pytest_asyncio.fixture
async def hex_client_with_mocks():
    """自带 DI override 的异步客户端 + MockLLMAdapter 实例。

    装配一个完全 in-memory 的 ChatService (LLM=Mock, Storage=Memory,
    Tool=Inproc 配 mock registry, Skill/Metric/Event 走最小 stub),
    覆盖 get_chat_service 工厂; 测试结束后还原依赖覆盖, 避免污染
    同一 app 上的其它测试。

    返回 (client, fake_svc, mock_llm), 测试可读 mock_llm.calls 校验
    LLM 实际收到了什么 messages。
    """
    mock_tool = MagicMock()
    mock_tool.execute.return_value = MagicMock(success=True, output="ok", error=None)
    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    mock_registry.get.return_value = mock_tool

    mock_llm = MockLLMAdapter(
        responses=[Message(role=Role.ASSISTANT, content="hello from hex")],
    )

    fake_svc = ChatService(
        llm=mock_llm,
        tools=InprocToolAdapter(registry=mock_registry),
        skills=MagicMock(),
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=StdoutEventAdapter(verbose=False),
    )

    saved_override = app.dependency_overrides.get(get_chat_service)
    app.dependency_overrides[get_chat_service] = lambda: fake_svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac, fake_svc, mock_llm
    finally:
        if saved_override is not None:
            app.dependency_overrides[get_chat_service] = saved_override
        else:
            app.dependency_overrides.pop(get_chat_service, None)


def _attachment_messages(messages: List[Any]) -> List[Any]:
    """从 LLM 调用收到的 messages 中过滤 system + 含 <attachments> 块的."""
    return [
        message
        for message in messages
        if message.role == Role.SYSTEM and "<attachments>" in (message.content or "")
    ]


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_hex_chat_injects_pptx_digest(hex_client_with_mocks, monkeypatch, tmp_path):
    """@foo.pptx 走 resolver.process 后, LLM 收到的 messages 应含 <attachments> 块."""
    client, fake_svc, mock_llm = hex_client_with_mocks

    pptx_path = tmp_path / "x.pptx"
    pptx_path.touch()
    monkeypatch.setattr(
        attachment_resolver, "_digest_ppt", lambda path, workspace: "PPT_FAKE_DIGEST"
    )

    sid = await fake_svc.storage.create_session()
    resp = await client.post(
        CHAT_PATH,
        json={
            "session_id": sid,
            "message": f"看 @{pptx_path} 怎么样",
            "workspace_path": str(tmp_path),
        },
    )
    assert resp.status_code == 200, resp.text

    assert len(mock_llm.calls) == 1
    messages = mock_llm.calls[0]["messages"]
    attachment_sys = _attachment_messages(messages)
    assert attachment_sys == [
        Message(
            role=Role.SYSTEM,
            content=(
                f"{ATTACHMENT_PROMPT_PREFIX}<attachments>\n"
                "=== x.pptx ===\n"
                "PPT_FAKE_DIGEST\n"
                "</attachments>"
            ),
        )
    ]


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_hex_chat_no_mention_no_injection(hex_client_with_mocks, monkeypatch, tmp_path):
    """无 @ mention 时 LLM 收到的 messages 不应包含 <attachments> 块."""
    client, fake_svc, mock_llm = hex_client_with_mocks

    process_calls: List[tuple] = []
    original_process = attachment_resolver.process

    def tracking_process(text, workspace):
        process_calls.append((text, workspace))
        return original_process(text, workspace)

    monkeypatch.setattr(attachment_resolver, "process", tracking_process)

    sid = await fake_svc.storage.create_session()
    resp = await client.post(
        CHAT_PATH,
        json={
            "session_id": sid,
            "message": "hello world",
            "workspace_path": str(tmp_path),
        },
    )
    assert resp.status_code == 200, resp.text

    assert process_calls == [("hello world", str(tmp_path))]
    assert len(mock_llm.calls) == 1
    messages = mock_llm.calls[0]["messages"]
    assert _attachment_messages(messages) == []


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_hex_chat_multi_doc_in_order(hex_client_with_mocks, monkeypatch, tmp_path):
    """@a.pptx @b.docx 产出按出现顺序的 attachment 块."""
    client, fake_svc, mock_llm = hex_client_with_mocks

    pptx_path = tmp_path / "a.pptx"
    docx_path = tmp_path / "b.docx"
    pptx_path.touch()
    docx_path.touch()
    monkeypatch.setattr(attachment_resolver, "_digest_ppt", lambda path, workspace: "P")
    monkeypatch.setattr(attachment_resolver, "_digest_word", lambda path, workspace: "W")

    sid = await fake_svc.storage.create_session()
    resp = await client.post(
        CHAT_PATH,
        json={
            "session_id": sid,
            "message": f"@{pptx_path} 然后 @{docx_path}",
            "workspace_path": str(tmp_path),
        },
    )
    assert resp.status_code == 200, resp.text

    assert len(mock_llm.calls) == 1
    messages = mock_llm.calls[0]["messages"]
    attachment_sys = _attachment_messages(messages)
    assert len(attachment_sys) == 1
    content = attachment_sys[0].content
    assert content.startswith(ATTACHMENT_PROMPT_PREFIX)
    assert content.index("=== a.pptx ===") < content.index("=== b.docx ===")
    assert "=== a.pptx ===\nP" in content
    assert "=== b.docx ===\nW" in content


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_hex_chat_attachment_block_not_persisted(
    hex_client_with_mocks, monkeypatch, tmp_path
):
    """T4.M2 闭包: attachment system message 不写入 storage.

    旧实现用 svc.storage.append_message(...) 持久化块, 后续 turn 会重发。
    新实现应在 run_turn 期间 inline prepend, 不留痕。
    """
    client, fake_svc, mock_llm = hex_client_with_mocks

    pptx_path = tmp_path / "x.pptx"
    pptx_path.touch()
    monkeypatch.setattr(attachment_resolver, "_digest_ppt", lambda path, workspace: "D")

    sid = await fake_svc.storage.create_session()
    resp = await client.post(
        CHAT_PATH,
        json={
            "session_id": sid,
            "message": f"看 @{pptx_path}",
            "workspace_path": str(tmp_path),
        },
    )
    assert resp.status_code == 200, resp.text

    # 持久化的 history 应只含 user + assistant (无 attachment system message)
    persisted = await fake_svc.storage.get_messages(sid)
    roles = [m.role for m in persisted]
    assert roles == [
        Role.USER,
        Role.ASSISTANT,
    ], f"attachment system message leaked into storage: roles={roles}"
    assert not any("<attachments>" in (m.content or "") for m in persisted)

    # 但当前 turn 的 LLM 调用应收到 attachment 块
    assert len(mock_llm.calls) == 1
    messages = mock_llm.calls[0]["messages"]
    assert _attachment_messages(messages), "current turn's LLM call lost the attachment block"


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_hex_chat_second_turn_attachment_not_replayed(
    hex_client_with_mocks, monkeypatch, tmp_path
):
    """T4.M2 闭包: 第二轮再发同 mention 时, 不应重复注入历史 turn 的 attachment 块."""
    client, fake_svc, mock_llm = hex_client_with_mocks

    pptx_path = tmp_path / "x.pptx"
    pptx_path.touch()
    monkeypatch.setattr(attachment_resolver, "_digest_ppt", lambda path, workspace: "D")

    sid = await fake_svc.storage.create_session()
    # 第一轮: 触发 attachment 块
    await client.post(
        CHAT_PATH,
        json={
            "session_id": sid,
            "message": f"first @{pptx_path}",
            "workspace_path": str(tmp_path),
        },
    )
    # 第二轮: 不带 mention
    await client.post(
        CHAT_PATH,
        json={
            "session_id": sid,
            "message": "second no mention",
            "workspace_path": str(tmp_path),
        },
    )

    assert len(mock_llm.calls) == 2
    second_messages = mock_llm.calls[1]["messages"]
    # 第二轮 LLM 收到的 messages 不应包含任何 attachment 块
    assert _attachment_messages(second_messages) == []
