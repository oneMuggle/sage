"""M3 权限与安全边界 — ChatService PermissionPreset 接线。

- AUDIT 预设下 write_file/delete_file/execute/shell 被拒。
- IMPLEMENT 预设下 write_file 正常。
- allowed_paths 越界被拒（preset=IMPLEMENT）。
- denied_tools 黑名单生效。
- 被拒时 tool_result 事件含 permission_decision=denied。
"""

from __future__ import annotations

from typing import List, Tuple
from unittest.mock import MagicMock

import pytest
from sage_core import Message, Role, ToolCall

from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.application.services.chat_service import ChatService
from backend.domain.tool_policy import ToolPolicy
from backend.orchestration.permission import PermissionPreset

pytestmark = pytest.mark.integration


class _RecordingEvents:
    def __init__(self) -> None:
        self.calls: List[Tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict) -> None:
        self.calls.append((event_type, payload))

    def lifecycle(self) -> List[Tuple[str, dict]]:
        return [(t, p) for t, p in self.calls if isinstance(p, dict) and "run_id" in p]


def _make_service(events, preset, *, allowed_paths=None, denied_tools=None, workspace_root=None):
    tool_call_msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(name="write_file", args={"path": "/tmp/x.txt", "content": "x"}, id="c1")
        ],
    )
    mock_tool = MagicMock()
    mock_tool.execute.return_value = MagicMock(success=True, output="ok", error=None)
    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    mock_registry.get.return_value = mock_tool
    policy = ToolPolicy(
        workspace_root=workspace_root,
        max_tool_calls_per_run=25,
    )
    return ChatService(
        llm=MockLLMAdapter(responses=[tool_call_msg]),
        tools=InprocToolAdapter(registry=mock_registry, policy=policy),
        skills=MagicMock(),
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=events,
        tool_policy=policy,
        permission_preset=preset,
        permission_allowed_paths=list(allowed_paths) if allowed_paths else None,
        permission_denied_tools=list(denied_tools) if denied_tools else None,
    )


@pytest.mark.asyncio()
async def test_audit_preset_denies_write_file():
    events = _RecordingEvents()
    svc = _make_service(events, PermissionPreset.AUDIT)

    sid = await svc.create_session()
    await svc.run_turn(sid, Message(role=Role.USER, content="go"))

    lc = events.lifecycle()
    last_payload = lc[-1][1]
    assert last_payload["status"] == "ok"
    tool_results = [p for t, p in lc if t == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["success"] is False
    assert "permission_denied" in (tool_results[0].get("error") or "")
    assert tool_results[0]["permission_decision"] == "denied"


@pytest.mark.asyncio()
async def test_implement_preset_allows_write_file():
    events = _RecordingEvents()
    svc = _make_service(events, PermissionPreset.IMPLEMENT)

    sid = await svc.create_session()
    await svc.run_turn(sid, Message(role=Role.USER, content="go"))

    lc = events.lifecycle()
    tool_results = [p for t, p in lc if t == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["success"] is True
    assert tool_results[0]["permission_decision"] == "allowed"


@pytest.mark.asyncio()
async def test_allowed_paths_outside_workspace_denied(tmp_path):
    """IMPLEMENT 预设 + allowed_paths=[tmp_path] + write_file 到 tmp_path.parent → 拒绝。"""
    events = _RecordingEvents()
    # pytest tmp_path.parent 在所有 test 间共享；用 unique 名字避免与 test_file_tool_safepath 串扰
    target = tmp_path.parent / "perm_outside_target.txt"
    try:
        tool_call_msg = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(
                    name="write_file",
                    args={"path": str(target), "content": "x"},
                    id="c1",
                )
            ],
        )
        mock_tool = MagicMock()
        mock_tool.execute.return_value = MagicMock(success=True, output="ok", error=None)
        mock_registry = MagicMock()
        mock_registry.list.return_value = []
        mock_registry.get.return_value = mock_tool
        policy = ToolPolicy(max_tool_calls_per_run=25)
        svc = ChatService(
            llm=MockLLMAdapter(responses=[tool_call_msg]),
            tools=InprocToolAdapter(registry=mock_registry, policy=policy),
            skills=MagicMock(),
            storage=MemoryStorageAdapter(),
            metrics=NoopMetricAdapter(),
            events=events,
            tool_policy=policy,
            permission_preset=PermissionPreset.IMPLEMENT,
            permission_allowed_paths=[str(tmp_path)],
        )

        sid = await svc.create_session()
        await svc.run_turn(sid, Message(role=Role.USER, content="go"))

        lc = events.lifecycle()
        tool_results = [p for t, p in lc if t == "tool_result"]
        assert len(tool_results) == 1
        assert tool_results[0]["success"] is False
        assert tool_results[0]["permission_decision"] == "denied"
        # 工具未被实际调用（permission 在工具执行前拦截）
        assert not target.exists()
    finally:
        target.unlink(missing_ok=True)


@pytest.mark.asyncio()
async def test_denied_tools_blacklist_denies_read_file():
    """IMPLEMENT 预设 + denied_tools=[read_file] → read_file 被拒。"""
    events = _RecordingEvents()
    tool_call_msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(name="read_file", args={"path": "/tmp/x.txt"}, id="c1")],
    )
    mock_tool = MagicMock()
    mock_tool.execute.return_value = MagicMock(success=True, output="ok", error=None)
    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    mock_registry.get.return_value = mock_tool
    policy = ToolPolicy(max_tool_calls_per_run=25)
    svc = ChatService(
        llm=MockLLMAdapter(responses=[tool_call_msg]),
        tools=InprocToolAdapter(registry=mock_registry, policy=policy),
        skills=MagicMock(),
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=events,
        tool_policy=policy,
        permission_preset=PermissionPreset.IMPLEMENT,
        permission_denied_tools=["read_file"],
    )

    sid = await svc.create_session()
    await svc.run_turn(sid, Message(role=Role.USER, content="go"))

    lc = events.lifecycle()
    tool_results = [p for t, p in lc if t == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["success"] is False
    assert tool_results[0]["permission_decision"] == "denied"


@pytest.mark.asyncio()
async def test_default_preset_is_implement_allows_write():
    """缺省 permission_preset=None → 等价 IMPLEMENT（向后兼容）。"""
    events = _RecordingEvents()
    tool_call_msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(name="write_file", args={"path": "/tmp/x.txt", "content": "x"}, id="c1")
        ],
    )
    mock_tool = MagicMock()
    mock_tool.execute.return_value = MagicMock(success=True, output="ok", error=None)
    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    mock_registry.get.return_value = mock_tool
    policy = ToolPolicy(max_tool_calls_per_run=25)
    svc = ChatService(
        llm=MockLLMAdapter(responses=[tool_call_msg]),
        tools=InprocToolAdapter(registry=mock_registry, policy=policy),
        skills=MagicMock(),
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=events,
        tool_policy=policy,
    )

    sid = await svc.create_session()
    await svc.run_turn(sid, Message(role=Role.USER, content="go"))

    lc = events.lifecycle()
    tool_results = [p for t, p in lc if t == "tool_result"]
    assert tool_results[0]["success"] is True


@pytest.mark.asyncio()
async def test_tool_result_event_carries_resolved_path():
    """M3: tool_result 事件 payload 补 resolved_path + permission_decision（审计可查）。"""
    events = _RecordingEvents()
    tool_call_msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(
                name="write_file",
                args={"path": "/tmp/audit_target.txt", "content": "x"},
                id="c1",
            )
        ],
    )
    mock_tool = MagicMock()
    mock_tool.execute.return_value = MagicMock(success=True, output="ok", error=None)
    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    mock_registry.get.return_value = mock_tool
    policy = ToolPolicy(max_tool_calls_per_run=25)
    svc = ChatService(
        llm=MockLLMAdapter(responses=[tool_call_msg]),
        tools=InprocToolAdapter(registry=mock_registry, policy=policy),
        skills=MagicMock(),
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=events,
        tool_policy=policy,
    )

    sid = await svc.create_session()
    await svc.run_turn(sid, Message(role=Role.USER, content="go"))

    lc = events.lifecycle()
    tool_results = [p for t, p in lc if t == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["resolved_path"] == "/tmp/audit_target.txt"
    assert tool_results[0]["permission_decision"] == "allowed"
