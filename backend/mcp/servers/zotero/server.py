"""Zotero MCP Server — expose local Zotero library to LLM agents.

Read-only access to a local Zotero SQLite database via MCP tools.
The LLM can search for references, retrieve item metadata, read
annotations, list collections, export BibTeX, and read PDF fulltext.

Tools exposed (7):
  - zotero_status: health check + library stats
  - zotero_search: search by title/abstract/author
  - zotero_get_item: full metadata for one item
  - zotero_get_annotations: PDF annotations for an item
  - zotero_list_collections: flat collection list
  - zotero_get_bibtex: BibTeX export for multiple items
  - zotero_read_pdf: chunked PDF fulltext (user-invoked)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional MCP import — same pattern as wiki/mcp_server.py
# ---------------------------------------------------------------------------

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool
except Exception as exc:  # noqa: BLE001 — optional integration must not break backend
    Server = None  # type: ignore[assignment,misc]
    stdio_server = None  # type: ignore[assignment]
    _MCP_IMPORT_ERROR = exc

    class TextContent:  # type: ignore[no-redef]
        """Fallback used when MCP is unavailable."""

        def __init__(self, *, type: str, text: str):
            self.type = type
            self.text = text

    @dataclass
    class Tool:  # type: ignore[no-redef]
        """Fallback tool descriptor for helper tests without MCP."""

        name: str
        description: str
        inputSchema: Dict[str, Any]  # noqa: N815

else:
    _MCP_IMPORT_ERROR = None


def _build_server() -> Optional[Server]:  # type: ignore[valid-type]
    if Server is None:
        return None
    try:
        return Server("sage-zotero")
    except Exception as exc:  # noqa: BLE001
        global _MCP_IMPORT_ERROR
        _MCP_IMPORT_ERROR = exc
        return None


server = _build_server()


def _handler_decorator(method_name: str):
    """Return an MCP decorator, or an identity decorator without MCP."""
    if server is None:
        return lambda function: function
    return getattr(server, method_name)()


def _require_mcp_runtime() -> None:
    """Raise an actionable error when the optional MCP runtime is unavailable."""
    if _MCP_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Zotero MCP server requires a compatible 'mcp' installation; "
            f"import failed with {type(_MCP_IMPORT_ERROR).__name__}: {_MCP_IMPORT_ERROR}"
        ) from _MCP_IMPORT_ERROR


# ---------------------------------------------------------------------------
# Lazy client construction — db_path comes from env var at runtime
# ---------------------------------------------------------------------------

_client = None


def _get_client():
    """Return a cached ZoteroClient (constructed lazily on first call)."""
    global _client
    if _client is None:
        from backend.zotero import ZoteroClient

        _client = ZoteroClient()
    return _client


# ---------------------------------------------------------------------------
# MCP tool definitions
# ---------------------------------------------------------------------------


@_handler_decorator("list_tools")
async def list_tools() -> List[Tool]:
    """List all available Zotero tools."""
    return [
        Tool(
            name="zotero_status",
            description=(
                "Check Zotero connection status and library statistics. "
                "Returns the database path, item count, collection count, tag count, "
                "and attachment count. Use this to verify Zotero is reachable before "
                "other operations."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="zotero_search",
            description=(
                "Search the Zotero library by title, abstract, or author name. "
                "Returns a summary of matching items including key, title, date, "
                "authors, tags, and item type. Optionally filter by collection or tag."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search text (matched against title, abstract, and author names, case-insensitive)",
                    },
                    "collection_key": {
                        "type": "string",
                        "description": "Optional: restrict results to this Zotero collection key",
                    },
                    "tag": {
                        "type": "string",
                        "description": "Optional: only include items with this tag",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 20)",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="zotero_get_item",
            description=(
                "Retrieve full metadata for a single Zotero item by its key. "
                "Returns all fields (title, date, abstract, DOI, URL, etc.), "
                "authors with creator types, tags, collection membership, "
                "child attachments (PDFs etc.), and child notes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "item_key": {
                        "type": "string",
                        "description": "The Zotero item key (e.g. 'ABCD1234')",
                    }
                },
                "required": ["item_key"],
            },
        ),
        Tool(
            name="zotero_get_annotations",
            description=(
                "Retrieve PDF annotations (highlights, underlines, notes, comments) "
                "for a Zotero item. Returns annotation text, type, color, page label, "
                "and comment for each annotation found in the item's attachments."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "item_key": {
                        "type": "string",
                        "description": "The Zotero item key (parent item, not the attachment)",
                    }
                },
                "required": ["item_key"],
            },
        ),
        Tool(
            name="zotero_list_collections",
            description=(
                "List Zotero collections (folders) as a flat list. Each entry "
                "includes its parentKey so callers can reconstruct the tree. "
                "If parent_key is given, only immediate children of that collection "
                "are returned; otherwise top-level collections are returned."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "parent_key": {
                        "type": "string",
                        "description": "Optional: collection key to list children of (omit for top-level)",
                    }
                },
            },
        ),
        Tool(
            name="zotero_get_bibtex",
            description=(
                "Generate BibTeX entries for one or more Zotero items. "
                "The output is compatible with Sage's office_parse_bibtex tool. "
                "Pass a list of item_keys to get multiple entries separated by blank lines."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "item_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of Zotero item keys",
                    }
                },
                "required": ["item_keys"],
            },
        ),
        Tool(
            name="zotero_read_pdf",
            description=(
                "Read the full text of a PDF attached to a Zotero item. "
                "User-invoked — do not call automatically. Returns a chunk of text "
                "from Zotero's FTS index if available, or reports the local PDF path "
                "for external extraction. Use chunk_offset + chunk_size for pagination."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "item_key": {
                        "type": "string",
                        "description": "The Zotero item key (parent item)",
                    },
                    "chunk_offset": {
                        "type": "integer",
                        "description": "Character offset for chunked reading (default: 0)",
                        "default": 0,
                    },
                    "chunk_size": {
                        "type": "integer",
                        "description": "Characters per chunk (default: 10000)",
                        "default": 10000,
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return in one call (default: 50000)",
                        "default": 50000,
                    },
                },
                "required": ["item_key"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# MCP tool dispatch
# ---------------------------------------------------------------------------


@_handler_decorator("call_tool")
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:  # noqa: PLR0911
    """Dispatch to the appropriate Zotero tool handler."""
    try:
        if name == "zotero_status":
            return await _zotero_status()
        elif name == "zotero_search":
            return await _zotero_search(arguments)
        elif name == "zotero_get_item":
            return await _zotero_get_item(arguments)
        elif name == "zotero_get_annotations":
            return await _zotero_get_annotations(arguments)
        elif name == "zotero_list_collections":
            return await _zotero_list_collections(arguments)
        elif name == "zotero_get_bibtex":
            return await _zotero_get_bibtex(arguments)
        elif name == "zotero_read_pdf":
            return await _zotero_read_pdf(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown Zotero tool: {name}")]
    except Exception as exc:
        logger.error(
            "Zotero MCP tool failed: name=%s error_type=%s", name, type(exc).__name__
        )
        return [TextContent(type="text", text=f"Error: Zotero tool '{name}' failed: {exc}")]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def _zotero_status() -> List[TextContent]:
    """Health check + library stats."""
    client = _get_client()
    health = client.health_check()
    if health["status"] == "ok":
        stats = client.get_stats()
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {"health": health, "stats": stats},
                    indent=2,
                    ensure_ascii=False,
                ),
            )
        ]
    return [TextContent(type="text", text=json.dumps(health, indent=2, ensure_ascii=False))]


async def _zotero_search(args: Dict[str, Any]) -> List[TextContent]:
    """Search items by title/abstract/author."""
    client = _get_client()
    query = args["query"]
    collection_key = args.get("collection_key")
    tag = args.get("tag")
    limit = args.get("limit", 20)
    results = client.search(query, collection_key=collection_key, tag=tag, limit=limit)
    return [
        TextContent(
            type="text",
            text=json.dumps(
                {"query": query, "total": len(results), "results": results},
                indent=2,
                ensure_ascii=False,
            ),
        )
    ]


async def _zotero_get_item(args: Dict[str, Any]) -> List[TextContent]:
    """Full metadata for one item."""
    client = _get_client()
    item_key = args["item_key"]
    item = client.get_item(item_key)
    return [TextContent(type="text", text=json.dumps(item, indent=2, ensure_ascii=False))]


async def _zotero_get_annotations(args: Dict[str, Any]) -> List[TextContent]:
    """PDF annotations for an item."""
    client = _get_client()
    item_key = args["item_key"]
    annotations = client.get_annotations(item_key)
    return [
        TextContent(
            type="text",
            text=json.dumps(
                {"item_key": item_key, "total": len(annotations), "annotations": annotations},
                indent=2,
                ensure_ascii=False,
            ),
        )
    ]


async def _zotero_list_collections(args: Dict[str, Any]) -> List[TextContent]:
    """List collections (flat list with parentKey)."""
    client = _get_client()
    parent_key = args.get("parent_key")
    collections = client.list_collections(parent_key=parent_key)
    return [
        TextContent(
            type="text",
            text=json.dumps(
                {"total": len(collections), "collections": collections},
                indent=2,
                ensure_ascii=False,
            ),
        )
    ]


async def _zotero_get_bibtex(args: Dict[str, Any]) -> List[TextContent]:
    """Generate BibTeX for multiple items."""
    client = _get_client()
    item_keys = args["item_keys"]
    bibtex = client.get_bibtex(list(item_keys))
    return [TextContent(type="text", text=bibtex)]


async def _zotero_read_pdf(args: Dict[str, Any]) -> List[TextContent]:
    """Read PDF fulltext (user-invoked, chunked)."""
    client = _get_client()
    item_key = args["item_key"]
    chunk_offset = args.get("chunk_offset", 0)
    chunk_size = args.get("chunk_size", 10000)
    max_chars = args.get("max_chars", 50000)
    result = client.read_pdf_fulltext(
        item_key,
        chunk_offset=chunk_offset,
        chunk_size=chunk_size,
        max_chars=max_chars,
    )
    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------


async def run_zotero_mcp_server() -> None:
    """Run the Zotero MCP Server (stdio JSON-RPC 2.0)."""
    _require_mcp_runtime()
    assert server is not None
    assert stdio_server is not None
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_zotero_mcp_server())
