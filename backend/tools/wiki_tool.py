"""Wiki / RAG tool wrappers (T7.5 / Task 3 step 5).

The agent loop now exposes Wiki search + RAG message preparation as two
LLM-callable tools:

* :class:`WikiSearchTool` -- thin wrapper around :func:`backend.wiki.search.
  search_wiki`. Returns the hit list; the LLM decides what to do with it.
* :class:`WikiAnswerTool` -- prepares the messages the LLM should consume
  to answer the user's query. Wraps :func:`backend.wiki.chat._build_chat_context`
  (the RAG retrieval) and :func:`backend.wiki.chat._build_rag_messages` (the
  prompt builder). Surfaces the prepared messages + citations to the caller
  so the orchestrator can drive the actual LLM call -- keeping the tool
  deterministic and easy to test.

Both tools share the same authorization shape:

1. ``requires_tool_context = True`` -- refuse with ``missing_tool_context``
   when the agent loop hasn't propagated a :class:`ToolExecutionContext`.
2. The context must carry a live ``session_id`` AND a live workspace binding
   (``get_active_workspace(conn, session_id, expected_generation=...)``
   returns non-None). Otherwise refuse with ``no_workspace_binding``.
3. Tool output never echoes the absolute ``workspace_path`` -- only the
   relative path components the LLM actually needs.

These wrappers sit on top of the existing Wiki modules so the LLM can ask
questions over the project wiki without round-tripping through the MCP server
-- it's the in-process equivalent.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.data.database import get_database
from backend.office.session_workspace import get_active_workspace
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import current_tool_context
from backend.wiki.search import SearchResponse, search_wiki

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────


def _resolve_bound_workspace(
    conn: sqlite3.Connection,
) -> Optional[Path]:
    """Return the binding's workspace path, or None when unbound / stale.

    Both tools share this resolution step. The result is the canonical
    absolute path the search / RAG helpers expect.
    """
    ctx = current_tool_context()
    if ctx is None or not ctx.session_id:
        return None
    binding = get_active_workspace(
        conn, ctx.session_id, expected_generation=ctx.binding_generation
    )
    if binding is None:
        return None
    return Path(binding.workspace_path)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from sync code.

    Used by ``WikiAnswerTool`` to call the existing async
    ``_build_chat_context`` helper. Handles three cases:

    * No running event loop -- ``asyncio.run`` (creates + tears down).
    * Already inside an event loop -- run on a fresh thread with its
      own loop and wait synchronously.
    """
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is None:
        return asyncio.run(coro)

    # Inside a running loop: schedule on a fresh thread with its own loop.
    import concurrent.futures

    def _runner() -> Any:
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_runner)
        return future.result()


# ──────────────────────────────────────────────────────────────────────
# WikiSearchTool
# ──────────────────────────────────────────────────────────────────────


class WikiSearchTool(BaseTool):
    """Search the bound workspace's wiki directory.

    Returns a list of search hits (``{title, path, snippet, score}``)
    ranked by token match score. The tool does NOT invoke the LLM --
    it just returns the raw retrieval results so the calling agent can
    decide whether to follow up with :class:`WikiAnswerTool` or surface
    the hits directly.
    """

    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="wiki_search",
            description=(
                "Search the project's wiki for pages matching a query. "
                "Returns ranked hits with title, relative path, snippet, "
                "and score. Use to locate wiki pages before reading them "
                "or building a RAG answer."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Natural-language search query (tokens are "
                            "extracted automatically; CJK + ASCII supported)."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            "Maximum number of hits to return "
                            "(default 20, hard cap 100)."
                        ),
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": ["query"],
            },
        )

    def execute(
        self,
        query: Optional[str] = None,
        limit: int = 20,
        **_kwargs: Any,
    ) -> ToolResult:
        ctx = current_tool_context()
        if ctx is None or not ctx.session_id:
            return ToolResult(success=False, error="missing_tool_context")

        if not isinstance(query, str) or not query.strip():
            return ToolResult(success=False, error="query_required")

        try:
            conn = get_database().get_connection()
        except Exception:
            return ToolResult(success=False, error="no_workspace_binding")

        project_root = _resolve_bound_workspace(conn)
        if project_root is None:
            return ToolResult(success=False, error="no_workspace_binding")

        # Bound the caller-supplied limit so a runaway "give me 10000"
        # request can't OOM the tool loop.
        effective_limit = max(1, min(int(limit or 20), 100))

        try:
            response: SearchResponse = search_wiki(
                project_root, query, limit=effective_limit
            )
        except Exception as exc:  # noqa: BLE001 -- surface as a safe error
            logger.warning("wiki_search failed: %s", exc)
            return ToolResult(success=False, error="search_failed")

        # Serialize to a JSON-safe payload. Relative paths only -- the
        # absolute workspace path never leaks to the LLM.
        items: List[Dict[str, Any]] = []
        for hit in response.results:
            items.append(
                {
                    "title": hit.title,
                    "path": hit.path,
                    "snippet": hit.snippet,
                    "score": hit.score,
                }
            )
        return ToolResult(
            success=True,
            content={
                "results": items,
                "total": response.total,
            },
        )


# ──────────────────────────────────────────────────────────────────────
# WikiAnswerTool
# ──────────────────────────────────────────────────────────────────────


class WikiAnswerTool(BaseTool):
    """Prepare a RAG answer for the user's query.

    Wraps :func:`backend.wiki.chat._build_chat_context` (retrieval) and
    :func:`backend.wiki.chat._build_rag_messages` (prompt assembly). The
    tool returns the prepared messages + citations so the orchestrator
    can drive the actual LLM call -- the tool itself does NOT call any
    LLM. This keeps the tool deterministic and easy to test.

    Returns:
        ``{success: True, content: {messages: [...], citations: [...]}}``
        where ``messages`` is the list of chat messages the LLM should
        consume and ``citations`` is the list of wiki paths used.
    """

    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="wiki_answer",
            description=(
                "Compose a RAG answer to a question about the project wiki. "
                "Returns the prepared chat messages (system + user) and "
                "the list of wiki pages cited. The caller drives the "
                "actual LLM call with these messages."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "User question to answer.",
                    },
                },
                "required": ["query"],
            },
        )

    def execute(
        self,
        query: Optional[str] = None,
        **_kwargs: Any,
    ) -> ToolResult:
        ctx = current_tool_context()
        if ctx is None or not ctx.session_id:
            return ToolResult(success=False, error="missing_tool_context")

        if not isinstance(query, str) or not query.strip():
            return ToolResult(success=False, error="query_required")

        try:
            conn = get_database().get_connection()
        except Exception:
            return ToolResult(success=False, error="no_workspace_binding")

        project_root = _resolve_bound_workspace(conn)
        if project_root is None:
            return ToolResult(success=False, error="no_workspace_binding")

        # Build a minimal ChatConfig for the retrieval helper. Embedding
        # failure inside _build_chat_context is non-fatal (it falls back
        # to token search); the dummy http_post is never actually called
        # when the embedding layer raises before hitting it.
        from backend.wiki.chat import (
            ChatConfig,
            _build_chat_context,
            _build_rag_messages,
        )

        config = ChatConfig(
            llm_base_url="http://localhost:0",
            llm_api_key="unused",
            llm_model="unused",
            embed_base_url="http://localhost:0",
            embed_api_key="unused",
            embed_model="unused",
        )

        async def _noop_http_post(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
            """Stand-in http_post: embedding layer is best-effort."""
            return {}

        try:
            context, citations, _stats = _run_async(
                _build_chat_context(
                    config=config,
                    project_root=project_root,
                    query=query,
                    http_post=_noop_http_post,
                )
            )
            messages = _build_rag_messages(query, context)
        except Exception as exc:  # noqa: BLE001 -- surface as a safe error
            logger.warning("wiki_answer failed: %s", exc)
            return ToolResult(success=False, error="rag_failed")

        # Return prepared messages + citations; the orchestrator drives
        # the actual LLM call from here.
        return ToolResult(
            success=True,
            content={
                "messages": messages,
                "citations": citations,
            },
        )


__all__ = ["WikiAnswerTool", "WikiSearchTool"]
