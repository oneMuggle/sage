"""Unit tests for the Wiki tool wrappers (T7.5 / Task 3 step 6).

The LLM tool loop now exposes Wiki search / answer via ``WikiSearchTool``
and ``WikiAnswerTool``. They wrap the existing :mod:`backend.wiki.search`
and :mod:`backend.wiki.chat` helpers but go through a session binding so
the workspace path is resolved safely (no path leak into tool output).

Contract:

- Both tools require an active ``ToolExecutionContext`` carrying a
  ``session_id``.
- The session must have a live workspace binding; otherwise the tool
  refuses with a safe error (not a path leak).
- ``WikiSearchTool`` wraps ``search_wiki`` and returns the results.
- ``WikiAnswerTool`` wraps ``_build_chat_context`` + ``_build_rag_messages``
  and returns the prepared messages + citations so the orchestrator can
  drive the LLM call.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple
from unittest.mock import patch

import pytest

from backend.data.database import Database
from backend.office.session_workspace import bind_session_workspace
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.wiki_tool import WikiAnswerTool, WikiSearchTool

pytestmark = pytest.mark.unit


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _seed_session(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (session_id, "t", 1, 1),
    )
    conn.commit()


def _ctx(session_id: str, binding_generation: int) -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id=session_id,
        stream_id="stream-x",
        binding_generation=binding_generation,
        office_doc_scope=frozenset(),
    )


def _seed_wiki_pages(project_root: Path) -> None:
    """Lay down two wiki pages the search can hit."""
    wiki = project_root / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "a.md").write_text(
        "# Alpha\n\nThis page covers the alpha topic in detail.\n",
        encoding="utf-8",
    )
    (wiki / "b.md").write_text(
        "# Beta\n\nThis page covers the beta topic.\n",
        encoding="utf-8",
    )


# ──────────────────────────────────────────────────────────────────────
# Schema + flag shape
# ──────────────────────────────────────────────────────────────────────


def test_wiki_search_requires_tool_context():
    assert WikiSearchTool().requires_tool_context is True


def test_wiki_answer_requires_tool_context():
    assert WikiAnswerTool().requires_tool_context is True


def test_wiki_search_schema_has_no_workspace_path_parameter():
    """Workspace path is resolved via session binding; the LLM never sees it."""
    schema = WikiSearchTool().schema
    params = schema.parameters.get("properties", {})
    assert "workspace_path" not in params
    assert "path" not in params
    assert "query" in params


def test_wiki_answer_schema_has_no_workspace_path_parameter():
    schema = WikiAnswerTool().schema
    params = schema.parameters.get("properties", {})
    assert "workspace_path" not in params
    assert "query" in params


# ──────────────────────────────────────────────────────────────────────
# Missing tool context
# ──────────────────────────────────────────────────────────────────────


def test_wiki_search_without_context_returns_missing_tool_context():
    tool = WikiSearchTool()
    result = tool.execute(query="anything")
    assert result.success is False
    assert result.error == "missing_tool_context"


def test_wiki_answer_without_context_returns_missing_tool_context():
    tool = WikiAnswerTool()
    result = tool.execute(query="anything")
    assert result.success is False
    assert result.error == "missing_tool_context"


# ──────────────────────────────────────────────────────────────────────
# Missing session binding
# ──────────────────────────────────────────────────────────────────────


def test_wiki_search_without_binding_returns_no_workspace_error(
    tmp_path: Path,
):
    """Tool context present but no live session-workspace binding →
    refuse with a safe error code. The LLM must never see the
    filesystem path of any fallback directory.
    """
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-unbound")
    # NB: no bind_session_workspace call.

    ctx = _ctx("sess-unbound", binding_generation=1)
    token = set_tool_context(ctx)
    try:
        with patch("backend.tools.wiki_tool.get_database", return_value=db):
            result = WikiSearchTool().execute(query="anything")
    finally:
        reset_tool_context(token)

    assert result.success is False
    assert result.error == "no_workspace_binding"


def test_wiki_answer_without_binding_returns_no_workspace_error(
    tmp_path: Path,
):
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-unbound")

    ctx = _ctx("sess-unbound", binding_generation=1)
    token = set_tool_context(ctx)
    try:
        with patch("backend.tools.wiki_tool.get_database", return_value=db):
            result = WikiAnswerTool().execute(query="anything")
    finally:
        reset_tool_context(token)

    assert result.success is False
    assert result.error == "no_workspace_binding"


# ──────────────────────────────────────────────────────────────────────
# Happy path — search
# ──────────────────────────────────────────────────────────────────────


def test_wiki_search_returns_results_from_search_wiki(tmp_path: Path):
    """WikiSearchTool must wrap ``search_wiki`` and surface results."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-wiki")
    project = tmp_path / "project"
    project.mkdir()
    _seed_wiki_pages(project)
    binding = bind_session_workspace(conn, "sess-wiki", str(project), now_ms=1)

    ctx = _ctx("sess-wiki", binding.generation)
    token = set_tool_context(ctx)
    try:
        with patch("backend.tools.wiki_tool.get_database", return_value=db):
            result = WikiSearchTool().execute(query="alpha", limit=5)
    finally:
        reset_tool_context(token)

    assert result.success is True
    items = result.content["results"]
    assert isinstance(items, list) and items
    titles = {item["title"] for item in items}
    assert "Alpha" in titles
    # Beta should not match a search for "alpha".
    assert "Beta" not in titles


def test_wiki_search_redacts_absolute_workspace_path(tmp_path: Path):
    """The tool result must never echo the binding's absolute workspace path."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-wiki")
    project = tmp_path / "project"
    project.mkdir()
    _seed_wiki_pages(project)
    binding = bind_session_workspace(conn, "sess-wiki", str(project), now_ms=1)

    ctx = _ctx("sess-wiki", binding.generation)
    token = set_tool_context(ctx)
    try:
        with patch("backend.tools.wiki_tool.get_database", return_value=db):
            result = WikiSearchTool().execute(query="alpha")
    finally:
        reset_tool_context(token)

    import json

    full_text = json.dumps(result.content, ensure_ascii=False)
    assert str(project.resolve()) not in full_text


# ──────────────────────────────────────────────────────────────────────
# Happy path — answer (RAG context preparation)
# ──────────────────────────────────────────────────────────────────────


def test_wiki_answer_returns_messages_and_citations(tmp_path: Path):
    """WikiAnswerTool wraps ``_build_chat_context`` + ``_build_rag_messages``.

    It must surface the prepared messages + citations to the caller so the
    orchestrator can drive the LLM call. The actual LLM invocation stays
    out of the tool — keeping the tool deterministic and easy to test.
    """
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-wiki")
    project = tmp_path / "project"
    project.mkdir()
    _seed_wiki_pages(project)
    binding = bind_session_workspace(conn, "sess-wiki", str(project), now_ms=1)

    captured: List[Tuple[str, str]] = []

    async def _fake_build_chat_context(config, project_root, query, http_post):
        captured.append((str(project_root), query))
        return (
            "\n--- 文件: wiki/a.md ---\nAlpha context.\n",
            ["wiki/a.md"],
            None,
        )

    def _fake_build_rag_messages(query, context):
        return [
            {"role": "system", "content": f"SYS:{context}"},
            {"role": "user", "content": f"USER:{query}"},
        ]

    ctx = _ctx("sess-wiki", binding.generation)
    token = set_tool_context(ctx)
    try:
        with patch("backend.tools.wiki_tool.get_database", return_value=db), \
             patch(
                 "backend.wiki.chat._build_chat_context",
                 _fake_build_chat_context,
             ), \
             patch(
                 "backend.wiki.chat._build_rag_messages",
                 _fake_build_rag_messages,
             ):
            result = WikiAnswerTool().execute(query="alpha")
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert captured == [(str(project.resolve()), "alpha")]
    assert result.content["messages"] == [
        {"role": "system", "content": "SYS:\n--- 文件: wiki/a.md ---\nAlpha context.\n"},
        {"role": "user", "content": "USER:alpha"},
    ]
    assert result.content["citations"] == ["wiki/a.md"]
    # No path leak.
    import json

    full_text = json.dumps(result.content, ensure_ascii=False)
    assert str(project.resolve()) not in full_text
