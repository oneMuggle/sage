"""验证 5 类审计事件落盘 audit.jsonl（PG3.2）。

覆盖范围
--------

- ``AuditEventType`` 5 类常量齐备（含 ``all()`` 返回 5 项）
- ``FileEventAdapter`` 写入 JSONL 格式正确（ts / type / payload）
- 5 类事件**至少**在 chat / session / settings / tool 路径上可被触发
  并写到 audit.jsonl：
  - ``chat_message_sent``  —— POST /chat
  - ``chat_response_completed`` —— POST /chat
  - ``tool_invoked``  —— POST /chat（LLM 返回 tool_calls）
  - ``session_created`` —— POST /sessions
  - ``settings_changed`` —— PUT /settings

测试策略
--------

单元层：直接调 ``FileEventAdapter`` 写 5 类事件到 tmp 路径，验证 JSONL 格式。
集成层：用 ``FileEventAdapter`` 替换 DI 注入的 events 端口，跑 hex 路径
完整端到端（POST /chat、POST /sessions、PUT /settings），验证 audit.jsonl
出现 5 类事件类型。
"""

from __future__ import annotations
from typing import Set

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sage_core import Message, Role, ToolCall

from backend.adapters.out.event.file_adapter import (
    AuditEventType,
    FileEventAdapter,
)
from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.api.hex_routes import get_chat_service
from backend.application.services.chat_service import ChatService
from backend.main import app

pytestmark = pytest.mark.integration


CHAT_PATH = "/api/v1/chat"
SESSIONS_PATH = "/api/v1/sessions"
SETTINGS_PATH = "/api/v1/settings"


# ==================== 单元层：AuditEventType + FileEventAdapter 落盘 ====================


def test_audit_event_type_has_5_constants():
    """AuditEventType 包含 spec § 6.1 全部 5 类常量。"""
    assert AuditEventType.CHAT_MESSAGE_SENT == "chat_message_sent"
    assert AuditEventType.CHAT_RESPONSE_COMPLETED == "chat_response_completed"
    assert AuditEventType.TOOL_INVOKED == "tool_invoked"
    assert AuditEventType.SESSION_CREATED == "session_created"
    assert AuditEventType.SETTINGS_CHANGED == "settings_changed"


def test_audit_event_type_all_returns_5_values():
    """``all()`` 返回 5 项且覆盖全部规范事件名。"""
    all_types = AuditEventType.all()
    assert len(all_types) == 5
    # 集合相等（顺序不敏感）
    assert set(all_types) == {
        "chat_message_sent",
        "chat_response_completed",
        "tool_invoked",
        "session_created",
        "settings_changed",
    }


def test_file_event_adapter_writes_5_audit_types(tmp_path: Path):
    """FileEventAdapter 把 5 类审计事件全部正确写入 JSONL。"""
    log = tmp_path / "audit.jsonl"
    adapter = FileEventAdapter(log_path=str(log))

    for event_type in AuditEventType.all():
        adapter.emit(event_type, {"k": event_type})

    content = log.read_text(encoding="utf-8")
    lines = [ln for ln in content.strip().split("\n") if ln]
    assert len(lines) == 5

    seen_types: Set[str] = set()
    for line in lines:
        evt = json.loads(line)
        assert "ts" in evt
        assert "type" in evt
        assert "payload" in evt
        seen_types.add(evt["type"])

    # 全部 5 类都落盘
    assert seen_types == set(AuditEventType.all())


# ==================== 集成层：hex 路径端到端触发 5 类事件 ====================


# PG-A1: local default "legacy" 同步 backend/main.py 临时 flip
# (见 main.py 注释)。 此前默认 "hex" 是因为 main.py 默认就是 "hex";
# 现在 main.py 改为 "legacy",这里同步改默认。
# 副作用:CI 默认(legacy)模式下本文件所有 _HEX_ONLY 测试被 skip,
# 失去 hex 模式审计测试覆盖;后续 PR 把 main.py 默认改回 "hex" 时
# 这里也要同步改回。
_API_MODE = os.environ.get("API_MODE", "legacy").lower()
_HEX_ONLY = pytest.mark.skipif(
    _API_MODE != "hex",
    reason=f"本文件测 hex 路径 5 类事件；当前 API_MODE={_API_MODE!r}（需 hex）",
)


def _read_event_types(log_path: Path) -> Set[str]:
    """从 audit.jsonl 读取所有事件 type 集合。"""
    if not log_path.exists():
        return set()
    content = log_path.read_text(encoding="utf-8")
    types: Set[str] = set()
    for line in content.strip().split("\n"):
        if not line:
            continue
        evt = json.loads(line)
        types.add(evt["type"])
    return types


@pytest_asyncio.fixture
async def audit_client(tmp_path: Path):
    """装配 FileEventAdapter（写 tmp 路径）的 hex 客户端。

    重定向 audit 日志到 ``tmp_path/audit.jsonl``，测试结束后还原 DI override。
    """
    log = tmp_path / "audit.jsonl"
    events = FileEventAdapter(log_path=str(log))

    mock_tool = MagicMock()
    mock_tool.execute.return_value = MagicMock(success=True, output="ok", error=None)
    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    mock_registry.get.return_value = mock_tool

    fake_svc = ChatService(
        llm=MockLLMAdapter(responses=[Message(role=Role.ASSISTANT, content="hi")]),
        tools=InprocToolAdapter(registry=mock_registry),
        skills=MagicMock(),
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=events,
    )

    saved_override = app.dependency_overrides.get(get_chat_service)
    app.dependency_overrides[get_chat_service] = lambda: fake_svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),  # type: ignore[arg-type]
            base_url="http://test",
        ) as ac:
            yield ac, log, fake_svc
    finally:
        if saved_override is not None:
            app.dependency_overrides[get_chat_service] = saved_override
        else:
            app.dependency_overrides.pop(get_chat_service, None)


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_chat_endpoint_emits_chat_message_and_completed(audit_client):
    """POST /chat 触发 ``chat_message_sent`` + ``chat_response_completed`` 2 类事件。"""
    client, log, fake_svc = audit_client

    sid = await fake_svc.create_session()
    resp = await client.post(CHAT_PATH, json={"session_id": sid, "message": "hi"})
    assert resp.status_code == 200, resp.text

    seen = _read_event_types(log)
    # session_created 由 create_session 触发
    assert "session_created" in seen
    # chat_message_sent + chat_response_completed 由 run_turn 触发
    assert "chat_message_sent" in seen
    assert "chat_response_completed" in seen


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_chat_service_create_session_emits_session_created(audit_client):
    """``ChatService.create_session()`` 触发 ``session_created`` 审计事件。"""
    _client, log, fake_svc = audit_client

    sid = await fake_svc.create_session(title="audit-test")
    assert sid  # 非空

    seen = _read_event_types(log)
    assert "session_created" in seen


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_settings_endpoint_emits_settings_changed(audit_client):
    """PUT /settings 触发 ``settings_changed`` 事件。"""
    client, log, _ = audit_client

    resp = await client.put(
        SETTINGS_PATH, json={"api_base_url": "https://api.example.com", "model": "gpt-x"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    # 响应中应包含被改的字段
    assert "api_base_url" in body["changed_fields"]
    assert "model" in body["changed_fields"]

    seen = _read_event_types(log)
    assert "settings_changed" in seen


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_5_event_types_e2e_via_hex_paths(audit_client):
    """端到端：触发全部 5 类事件，验证全部落盘。

    步骤：
    1. ``ChatService.create_session()``  → session_created
    2. POST /chat     → chat_message_sent + chat_response_completed
    3. PUT /settings  → settings_changed

    5 类中的 ``tool_invoked`` 需要 LLM 返回 tool_calls，由独立的
    ``test_tool_invoked_event_recorded_when_llm_returns_tool_calls`` 覆盖。
    """
    client, log, fake_svc = audit_client

    # Step 1: session_created（通过 ChatService，不走 HTTP 以避免与 legacy /sessions 冲突）
    sid = await fake_svc.create_session(title="audit-e2e")
    assert sid

    # Step 2: chat_message_sent + chat_response_completed
    resp = await client.post(CHAT_PATH, json={"session_id": sid, "message": "hi"})
    assert resp.status_code == 200

    # Step 3: settings_changed
    resp = await client.put(SETTINGS_PATH, json={"model": "gpt-x"})
    assert resp.status_code == 200

    # 验证 4 类已在 audit.jsonl
    seen = _read_event_types(log)
    assert "session_created" in seen
    assert "chat_message_sent" in seen
    assert "chat_response_completed" in seen
    assert "settings_changed" in seen
    assert len(seen) >= 4


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_tool_invoked_event_recorded_when_llm_returns_tool_calls(tmp_path: Path):
    """LLM 返回 tool_calls 时，tool_invoked 事件被 emit 并落盘。"""
    # 构造含 tool_calls 的 mock LLM 响应
    tool_call_msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(name="echo", args={"text": "hi"}, id="call-1"),
        ],
    )
    # 第二次响应（无 tool_calls）以结束轮次
    final_msg = Message(role=Role.ASSISTANT, content="done")

    mock_tool = MagicMock()
    mock_tool.execute.return_value = MagicMock(success=True, output="echo-output", error=None)
    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    mock_registry.get.return_value = mock_tool

    log = tmp_path / "audit.jsonl"
    events = FileEventAdapter(log_path=str(log))
    fake_svc = ChatService(
        llm=MockLLMAdapter(responses=[tool_call_msg, final_msg]),
        tools=InprocToolAdapter(registry=mock_registry),
        skills=MagicMock(),
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=events,
    )

    saved_override = app.dependency_overrides.get(get_chat_service)
    app.dependency_overrides[get_chat_service] = lambda: fake_svc
    try:
        sid = await fake_svc.create_session()
        # 直接调 ChatService.run_turn 触发 tool_calls 分支
        await fake_svc.run_turn(sid, Message(role=Role.USER, content="trigger tool"))
    finally:
        if saved_override is not None:
            app.dependency_overrides[get_chat_service] = saved_override
        else:
            app.dependency_overrides.pop(get_chat_service, None)

    seen = _read_event_types(log)
    assert "tool_invoked" in seen
    # 同时还应至少包含 session_created + chat_message_sent + chat_response_completed
    assert "session_created" in seen
    assert "chat_message_sent" in seen
    assert "chat_response_completed" in seen
