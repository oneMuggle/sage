"""Integration tests for ``/chat/stream`` + Office tool context wiring (Task 9).

Verifies the legacy producer correctly:

1. Captures the :class:`AuthorizedOfficeRequest` from Task 6 authorization.
2. Builds a :class:`ToolExecutionContext` from it and calls
   ``set_tool_context`` before ``agent.run_loop`` starts.
3. Calls ``reset_tool_context`` in ``finally`` so the ContextVar does not
   leak across requests.
4. With no binding / no refs, a context with an empty office scope is
   still set (F2: ordinary chat needs it for artifact recording) and
   Office schemas stay hidden from ``get_schemas_for_llm``.
5. A rebind between authorization and tool execution fails closed (stale
   generation in the context produces empty list / not-found results).

The tests mock ``SageAgent.run_loop`` to observe what the producer set up
and to exercise the context from inside the producer task.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.main import app
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.session_workspace import (
    bind_session_workspace,
    revoke_session_workspace,
)
from backend.office.storage import save_document
from backend.tools.context import current_tool_context

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"
SESSION_ID = "office-tools-test-session"


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _get_db_connection() -> sqlite3.Connection:
    from backend.data import database as db_mod

    assert db_mod._db is not None
    return db_mod._db.get_connection()


def _insert_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "t", 1, 1),
    )
    conn.commit()


def _make_doc(
    *,
    doc_id: str,
    workspace_path: str,
    doc_type: OfficeDocType = OfficeDocType.WORD,
    original_filename: str = "doc.docx",
) -> OfficeDocumentSummary:
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=doc_type,
        original_filename=original_filename,
        generated_filename=f"{doc_id}.docx",
        status=OfficeDocStatus.GENERATED,
        created_at=1_700_000_000_000,
        updated_at=1_700_000_000_000,
        metadata=OfficeDocumentMetadata(file_size_bytes=1024),
    )


def _registry_size() -> int:
    return len(app.state.streams._entries) if hasattr(app.state, "streams") else 0


# ──────────────────────────────────────────────────────────────────────
# 1. No binding / no refs -> Office schemas hidden + no context set
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_no_binding_sets_empty_scope_tool_context(client, tmp_path: Path):
    """Legacy path (no refs, no binding) -> producer sets a context with
    an empty office scope. F2 (2026-08-12): 普通聊天也必须设置
    ToolExecutionContext（binding_generation=0 + 空 scope），否则 write_file
    等工具的 artifact 记录因 current_tool_context() 为 None 静默早退。
    Office 工具仍因空 scope 从 get_schemas_for_llm 隐藏。
    """
    conn = _get_db_connection()
    _insert_session(conn, SESSION_ID)

    captured_contexts: List[object] = []

    async def mock_run_loop(messages, **kwargs):
        # Inside the producer task, current_tool_context() must be set even
        # without a binding — empty scope, generation 0.
        captured_contexts.append(current_tool_context())
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="ok")

    with patch("backend.api.legacy_routes.SageAgent") as mock_agent:
        mock_agent.return_value.run_loop = mock_run_loop

        response = await client.post(
            CHAT_STREAM_PATH,
            json={"session_id": SESSION_ID, "message": "hello"},
        )
        assert response.status_code == 200, response.text
        stream_id = response.json()["streamId"]
        attach = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
        assert attach.status_code == 200

    # No binding -> still a context, but generation 0 + empty scope.
    assert len(captured_contexts) == 1
    ctx = captured_contexts[0]
    assert ctx is not None
    assert ctx.binding_generation == 0
    assert ctx.office_doc_scope == frozenset()


# ──────────────────────────────────────────────────────────────────────
# 2. Active binding + refs -> context set + reset around run_loop
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_active_binding_sets_and_resets_tool_context(client, tmp_path: Path):
    """Active binding + refs -> producer sets ToolExecutionContext before
    run_loop and resets it afterwards (verified via current_tool_context).
    """
    conn = _get_db_connection()
    _insert_session(conn, SESSION_ID)
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, SESSION_ID, str(work), now_ms=1000)
    save_document(
        conn,
        _make_doc(
            doc_id="doc-a",
            workspace_path=str(work.resolve()),
            original_filename="a.docx",
        ),
    )

    captured_inside: List[object] = []

    async def mock_run_loop(messages, **kwargs):
        ctx_inside = current_tool_context()
        captured_inside.append(ctx_inside)
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="ok")

    with patch("backend.api.legacy_routes.SageAgent") as mock_agent:
        mock_agent.return_value.run_loop = mock_run_loop

        response = await client.post(
            CHAT_STREAM_PATH,
            json={
                "session_id": SESSION_ID,
                "message": "summarize @a.docx",
                "workspace_path": binding.workspace_path,
                "office_refs": [
                    {"doc_id": "doc-a", "doc_type": "word", "filename": "a.docx"},
                ],
            },
        )
        assert response.status_code == 200, response.text
        stream_id = response.json()["streamId"]
        attach = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
        assert attach.status_code == 200

    # During run_loop: context is set and matches the authorization.
    assert len(captured_inside) == 1
    ctx = captured_inside[0]
    assert ctx is not None
    assert ctx.session_id == SESSION_ID
    assert ctx.binding_generation == binding.generation
    assert "doc-a" in ctx.office_doc_scope

    # After producer: context is reset (the caller task sees None).
    assert current_tool_context() is None


# ──────────────────────────────────────────────────────────────────────
# 3. Rebind between auth and execution fails closed
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_rebind_between_auth_and_tool_execution_fails_closed(client, tmp_path: Path):
    """If the binding is revoked between authorization and tool execution,
    the ToolExecutionContext carries a stale generation. OfficeToolService
    must fail closed (return empty list / not found) under that generation.
    """
    conn = _get_db_connection()
    _insert_session(conn, SESSION_ID)
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, SESSION_ID, str(work), now_ms=1000)
    save_document(
        conn,
        _make_doc(
            doc_id="doc-a",
            workspace_path=str(work.resolve()),
            original_filename="a.docx",
        ),
    )

    captured_generations: List[int] = []

    async def mock_run_loop(messages, **kwargs):
        ctx = current_tool_context()
        if ctx is not None:
            captured_generations.append(ctx.binding_generation)
            # Simulate a rebind happening between authorization and the
            # tool call: revoke the binding so the captured generation
            # becomes stale.
            revoke_session_workspace(conn, SESSION_ID, now_ms=2000)
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="ok")

    with patch("backend.api.legacy_routes.SageAgent") as mock_agent:
        mock_agent.return_value.run_loop = mock_run_loop

        response = await client.post(
            CHAT_STREAM_PATH,
            json={
                "session_id": SESSION_ID,
                "message": "summarize @a.docx",
                "workspace_path": binding.workspace_path,
                "office_refs": [
                    {"doc_id": "doc-a", "doc_type": "word", "filename": "a.docx"},
                ],
            },
        )
        assert response.status_code == 200, response.text
        stream_id = response.json()["streamId"]
        attach = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
        assert attach.status_code == 200

    # The context the producer saw still carries the pre-rebind generation.
    assert captured_generations == [binding.generation]

    # After the revoke, calling OfficeToolService.list with the captured
    # (now stale) generation returns an empty list (indistinguishable
    # from "no documents").
    from backend.office.tool_service import OfficeToolService

    service = OfficeToolService()
    result = service.list(conn, SESSION_ID, binding.generation)
    assert result == []


# ──────────────────────────────────────────────────────────────────────
# 4. With no binding, Office schemas remain hidden from the LLM
# ──────────────────────────────────────────────────────────────────────


def test_office_tools_hidden_from_llm_without_context():
    """Without an active ToolExecutionContext, office_list / office_read
    are not exposed in get_schemas_for_llm output.
    """
    from backend.tools import register_all_tools
    from backend.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_all_tools(registry)

    # No set_tool_context() call -> current_tool_context() returns None.
    schemas = registry.get_schemas_for_llm()
    names = {s["name"] for s in schemas}
    assert "office_list" not in names
    assert "office_read" not in names
    # Sanity: normal tools still visible.
    assert "read_file" in names


def test_office_tools_visible_to_llm_with_context():
    """With an active ToolExecutionContext, office_list / office_read are
    exposed alongside normal tools.
    """
    from backend.tools import register_all_tools
    from backend.tools.context import (
        ToolExecutionContext,
        reset_tool_context,
        set_tool_context,
    )
    from backend.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_all_tools(registry)

    ctx = ToolExecutionContext(
        session_id="sess-x",
        stream_id="stream-x",
        binding_generation=1,
        office_doc_scope=frozenset(),
    )
    token = set_tool_context(ctx)
    try:
        schemas = registry.get_schemas_for_llm()
        names = {s["name"] for s in schemas}
        assert "office_list" in names
        assert "office_read" in names
        assert "read_file" in names
    finally:
        reset_tool_context(token)
