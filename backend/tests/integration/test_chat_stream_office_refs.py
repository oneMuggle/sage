"""/chat/stream integration tests for ChatOfficeRef authorization (Task 6).

Verifies that ``legacy_routes.chat_stream_create`` calls
:func:`backend.office.chat_refs.authorize_chat_office_request` synchronously
before creating a stream id, and that domain errors map to the correct
HTTP status codes:

- no binding + refs        -> 403 (WorkspaceNotBoundError)
- active binding + refs    -> 200 (streamId issued + producer started)
- workspace_path mismatch  -> 400 (WorkspacePathMismatchError)
- scoped doc miss          -> 404 (WorkspaceDocumentNotFoundError)

Critically: a failed authorization MUST NOT leave a stream id in the
StreamRegistry — the route raises HTTPException before ``registry.create``
is invoked.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional
from unittest.mock import patch

import pytest

from backend.main import app
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.session_workspace import bind_session_workspace
from backend.office.storage import save_document

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"
SESSION_ID = "office-refs-test-session"


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _get_db_connection() -> sqlite3.Connection:
    """Return the live test DB connection from the global Database singleton."""
    from backend.data import database as db_mod

    assert db_mod._db is not None, "setup_test_db fixture must run first"
    return db_mod._db.get_connection()


def _insert_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "新对话", 1, 1),
    )
    conn.commit()


def _make_doc(
    *,
    doc_id: str,
    workspace_path: str,
    doc_type: OfficeDocType = OfficeDocType.WORD,
    original_filename: Optional[str] = "doc.docx",
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
# Tests
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_office_refs_without_binding_returns_403_and_no_registry_entry(
    client, tmp_path: Path
):
    """No active binding + non-empty office_refs -> 403; stream id never created."""
    conn = _get_db_connection()
    _insert_session(conn, SESSION_ID)

    # IMPORTANT: no bind_session_workspace call here — session is unbound.

    refs = [{"doc_id": "doc-a", "doc_type": "word", "filename": "a.docx"}]
    response = await client.post(
        CHAT_STREAM_PATH,
        json={
            "session_id": SESSION_ID,
            "message": "hello",
            "office_refs": refs,
        },
    )
    assert response.status_code == 403, response.text
    body = response.json()
    assert body.get("detail", {}).get("type") == "workspace_not_bound"

    # Authorization failed -> no stream id was issued.
    assert _registry_size() == 0


@pytest.mark.asyncio()
async def test_office_refs_with_active_binding_starts_stream(
    client, tmp_path: Path
):
    """Active binding + matching refs -> 200; producer runs and yields events."""
    from backend.core.legacy.agent_state import AgentEvent, AgentState

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

    captured_messages: List[List[dict]] = []

    async def mock_run_loop(messages, **kwargs):
        captured_messages.append([dict(m) for m in messages])
        yield AgentEvent(state=AgentState.THINKING, iteration=0)

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
        # Drain the stream so the producer completes.
        attach = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
        assert attach.status_code == 200, attach.text

    # Authorization succeeded -> streamId was issued AND producer ran.
    assert len(captured_messages) == 1


@pytest.mark.asyncio()
async def test_workspace_path_mismatch_returns_400_and_no_registry_entry(
    client, tmp_path: Path
):
    """Active binding + workspace_path that doesn't match -> 400."""
    conn = _get_db_connection()
    _insert_session(conn, SESSION_ID)
    work = tmp_path / "work"
    work.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    bind_session_workspace(conn, SESSION_ID, str(work), now_ms=1000)
    save_document(
        conn,
        _make_doc(doc_id="doc-a", workspace_path=str(work.resolve())),
    )

    refs = [{"doc_id": "doc-a", "doc_type": "word", "filename": "doc.docx"}]
    response = await client.post(
        CHAT_STREAM_PATH,
        json={
            "session_id": SESSION_ID,
            "message": "hello",
            "workspace_path": str(other.resolve()),
            "office_refs": refs,
        },
    )
    assert response.status_code == 400, response.text
    assert _registry_size() == 0


@pytest.mark.asyncio()
async def test_unknown_doc_ref_returns_404_and_no_registry_entry(
    client, tmp_path: Path
):
    """Active binding + unknown doc id -> 404; no stream id issued."""
    conn = _get_db_connection()
    _insert_session(conn, SESSION_ID)
    work = tmp_path / "work"
    work.mkdir()
    bind_session_workspace(conn, SESSION_ID, str(work), now_ms=1000)

    refs = [{"doc_id": "ghost", "doc_type": "word", "filename": "g.docx"}]
    response = await client.post(
        CHAT_STREAM_PATH,
        json={
            "session_id": SESSION_ID,
            "message": "hello",
            "office_refs": refs,
        },
    )
    assert response.status_code == 404, response.text
    assert _registry_size() == 0


@pytest.mark.asyncio()
async def test_no_office_refs_falls_through_to_legacy_path(
    client, tmp_path: Path
):
    """Empty office_refs + workspace_path -> 200; attachment_resolver still runs."""
    from backend.core.legacy.agent_state import AgentEvent, AgentState

    conn = _get_db_connection()
    _insert_session(conn, SESSION_ID)

    captured_messages: List[List[dict]] = []

    async def mock_run_loop(messages, **kwargs):
        captured_messages.append([dict(m) for m in messages])
        yield AgentEvent(state=AgentState.THINKING, iteration=0)

    with patch("backend.api.legacy_routes.SageAgent") as mock_agent:
        mock_agent.return_value.run_loop = mock_run_loop

        response = await client.post(
            CHAT_STREAM_PATH,
            json={
                "session_id": SESSION_ID,
                "message": "hello",
                "workspace_path": str(tmp_path),
                # No office_refs -> legacy attachment_resolver path.
            },
        )
        assert response.status_code == 200, response.text
        stream_id = response.json()["streamId"]
        attach = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
        assert attach.status_code == 200

    assert len(captured_messages) == 1
