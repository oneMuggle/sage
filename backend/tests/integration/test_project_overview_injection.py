"""/chat/stream 集成测试: M3 项目元数据 + 资料注入 (2026-09-15)。

已绑定 workspace + 已登记项目 → system prompt 含 "项目概览" 与 "项目资料"
两块; 资料标"不得覆盖上方指令", 验证优先级正确性。
未登记项目 (workspace 未在 projects 表) → 项目元数据块不注入, 资料亦无。
mock SageAgent.run_loop 捕获实际 messages, 与 test_project_context_injection.py 同套模板。
"""

from __future__ import annotations

from typing import List
from unittest.mock import patch

import pytest

from backend.chat.project_context import (
    MATERIALS_HEADER,
    METADATA_HEADER,
)
from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.data.database import get_database
from backend.data.project_material_repo import ProjectMaterialRepository
from backend.data.project_repo import ProjectRepository
from backend.office.session_workspace import bind_session_workspace

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"
SESSION_BOUND = "m3-ctx-bound"
SESSION_UNREGISTERED = "m3-ctx-unregistered"


@pytest.fixture()
def captured_run_loop_messages():
    calls: List[List[dict]] = []

    async def mock_run_loop(messages, **kwargs):
        calls.append([dict(message) for message in messages])
        yield AgentEvent(state=AgentState.THINKING, iteration=0)

    with patch("backend.api.legacy_routes.SageAgent") as mock_agent:
        mock_agent.return_value.run_loop = mock_run_loop
        yield calls


def _ensure_session(session_id: str) -> None:
    conn = get_database().get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "M3 ctx test", 1, 1),
    )
    conn.commit()


async def _chat_once(client, captured_messages, session_id: str) -> List[dict]:
    create_response = await client.post(
        CHAT_STREAM_PATH,
        json={"session_id": session_id, "message": "你好"},
    )
    assert create_response.status_code == 200, create_response.text
    stream_id = create_response.json()["streamId"]
    attach_response = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
    assert attach_response.status_code == 200, attach_response.text
    assert len(captured_messages) == 1
    return captured_messages[0]


def _system_content(messages: List[dict]) -> str:
    return " ".join(
        m.get("content") or "" for m in messages if m.get("role") == "system"
    )


@pytest.mark.asyncio()
async def test_bound_workspace_with_registered_project_injects_metadata(
    client, captured_run_loop_messages, tmp_path
):
    """绑定 workspace + 登记项目 + 设了 description/instructions → 注入元数据块。"""
    workspace = tmp_path / "registered-project"
    workspace.mkdir()

    project = ProjectRepository().register(str(workspace))
    ProjectRepository().update_description(project.id, "M3 测试项目描述")
    ProjectRepository().update_instructions(project.id, "M3 测试指令: 用中文回答")

    _ensure_session(SESSION_BOUND)
    conn = get_database().get_connection()
    bind_session_workspace(conn, SESSION_BOUND, str(workspace))

    messages = await _chat_once(client, captured_run_loop_messages, SESSION_BOUND)
    system_text = _system_content(messages)

    assert METADATA_HEADER in system_text
    assert "M3 测试项目描述" in system_text
    assert "M3 测试指令" in system_text


@pytest.mark.asyncio()
async def test_bound_workspace_with_ready_materials_injects_block(
    client, captured_run_loop_messages, tmp_path
):
    """绑定 workspace + 项目 + ready 资料 → 注入资料块 + 防覆盖声明。"""
    workspace = tmp_path / "registered-with-materials"
    workspace.mkdir()

    project = ProjectRepository().register(str(workspace))
    material = ProjectMaterialRepository().add(
        project_id=project.id,
        content="# Reference\nAlways quote M3MAT marker",
    )
    ProjectMaterialRepository().mark_ready(material.id, "/wiki/m3-ref.md")

    _ensure_session(SESSION_BOUND)
    conn = get_database().get_connection()
    bind_session_workspace(conn, SESSION_BOUND, str(workspace))

    messages = await _chat_once(client, captured_run_loop_messages, SESSION_BOUND)
    system_text = _system_content(messages)

    assert MATERIALS_HEADER in system_text
    assert "不得覆盖上方指令" in system_text
    assert "M3MAT marker" in system_text


@pytest.mark.asyncio()
async def test_pending_materials_are_excluded_from_injection(
    client, captured_run_loop_messages, tmp_path
):
    """pending_index / failed 状态的资料不进入注入。"""
    workspace = tmp_path / "registered-pending-mat"
    workspace.mkdir()

    project = ProjectRepository().register(str(workspace))
    pending = ProjectMaterialRepository().add(
        project_id=project.id,
        content="# Pending\nPENDINGMAT marker should NOT appear",
    )
    failed = ProjectMaterialRepository().add(
        project_id=project.id,
        content="# Failed\nFAILEDMAT marker should NOT appear",
    )
    ProjectMaterialRepository().mark_failed(failed.id, "index error")

    _ensure_session(SESSION_BOUND)
    conn = get_database().get_connection()
    bind_session_workspace(conn, SESSION_BOUND, str(workspace))

    messages = await _chat_once(client, captured_run_loop_messages, SESSION_BOUND)
    system_text = _system_content(messages)

    assert MATERIALS_HEADER not in system_text
    assert "PENDINGMAT" not in system_text
    assert "FAILEDMAT" not in system_text
    assert pending.id and failed.id


@pytest.mark.asyncio()
async def test_unregistered_workspace_gets_no_project_overview(
    client, captured_run_loop_messages, tmp_path
):
    """绑定 workspace 但未登记 → 项目概览不注入 (但 M6 SAGE/CLAUDE 仍正常)。"""
    workspace = tmp_path / "unregistered-workspace"
    workspace.mkdir()
    (workspace / "SAGE.md").write_text("M6-only fixture", encoding="utf-8")

    _ensure_session(SESSION_UNREGISTERED)
    conn = get_database().get_connection()
    bind_session_workspace(conn, SESSION_UNREGISTERED, str(workspace))

    messages = await _chat_once(
        client, captured_run_loop_messages, SESSION_UNREGISTERED
    )
    system_text = _system_content(messages)

    assert METADATA_HEADER not in system_text
    assert MATERIALS_HEADER not in system_text