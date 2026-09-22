"""Zotero REST API routes — read-only library access for the settings UI.

Endpoints
---------
GET  /zotero/status       — health check + library stats (always 200; error in body)
GET  /zotero/search       — search items (?q=&collection_key=&tag=&limit=)
GET  /zotero/items/{key}  — single item detail
GET  /zotero/items/{key}/annotations — annotations for an item
GET  /zotero/collections  — list collections (?parent_key= for children)
POST /zotero/path         — persist custom Zotero DB path to settings_repo

All endpoints return 503 when Zotero is unavailable (no DB found / locked),
so the frontend can show a friendly "configure path" or "database locked"
message instead of a generic 500.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["zotero"])

# Lazy singleton — instantiated on first request to avoid startup cost when
# Zotero is not used. Re-created when db_path changes (see /path POST).
_client: Any | None = None
_client_db_path: str | None = None


def _get_configured_db_path() -> str | None:
    """Return the user-configured Zotero DB path from settings_repo, if any."""
    try:
        from backend.services.settings_repo import SettingsRepo

        repo = SettingsRepo()
        return repo.get("zotero_db_path") or os.environ.get("ZOTERO_DB_PATH")
    except Exception:
        return os.environ.get("ZOTERO_DB_PATH")


def _get_client(db_path_override: str | None = None) -> Any:
    """Return (or create) the ZoteroClient singleton.

    Raises HTTPException(503) if the database is not found or locked.
    """
    from backend.zotero import ZoteroClient
    from backend.zotero.exceptions import (
        ZoteroDatabaseLockedError,
        ZoteroDatabaseNotFoundError,
    )

    configured = db_path_override or _get_configured_db_path()

    global _client, _client_db_path
    if _client is not None and _client_db_path == configured:
        return _client

    try:
        _client = ZoteroClient(db_path=Path(configured) if configured else None)
        _client_db_path = configured
        return _client
    except (ZoteroDatabaseNotFoundError, ZoteroDatabaseLockedError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Response shapes (returned as dicts; documented for the frontend client)
# ---------------------------------------------------------------------------
#
# GET /zotero/status — 200 always (error in body):
#   { available: bool, db_path: str|null, error: str|null,
#     stats: { items: int, collections: int, tags: int, attachments: int }|null }
#
# GET /zotero/search — list of:
#   { key: str, title: str, item_type: str, year: int|null,
#     authors: list[str], abstract: str|null,
#     collections: list[str], tags: list[str], date_added: str|null }
#
# GET /zotero/items/{key}:
#   { key, title, item_type, year, authors, abstract,
#     collections: list[{key, name}], tags, date_added, date_modified,
#     extra, doi, url, attachments: list[{key, filename, path}] }
#
# GET /zotero/collections — list of:
#   { key, name, parent_key, item_count, version }
#
# GET /zotero/items/{key}/annotations — list of:
#   { key, type, text, comment, color, page_label, date_added }
#
# Dates: ISO 8601 UTC (Zotero SQLite dateAdded format).
# ---------------------------------------------------------------------------


@router.get("/status")
def get_status() -> dict[str, Any]:
    """Return Zotero connection status and library stats.

    Returns available=false (not 5xx) when the DB is missing or locked,
    so the settings UI can show a friendly configuration prompt.
    """
    from backend.zotero.exceptions import (
        ZoteroDatabaseLockedError,
        ZoteroDatabaseNotFoundError,
    )

    configured = _get_configured_db_path()
    try:
        client = _get_client()
        stats = client.get_stats()
        return {
            "available": True,
            "db_path": str(client.db_path),
            "error": None,
            "stats": stats,
        }
    except HTTPException as exc:
        return {
            "available": False,
            "db_path": configured,
            "error": exc.detail,
            "stats": None,
        }
    except (ZoteroDatabaseNotFoundError, ZoteroDatabaseLockedError) as exc:
        return {
            "available": False,
            "db_path": configured,
            "error": str(exc),
            "stats": None,
        }


@router.get("/search")
def search_items(
    q: str = Query("", description="Search query (title, abstract, author)"),
    collection_key: Optional[str] = Query(None, description="Filter by collection"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
) -> list[dict[str, Any]]:
    """Search library items."""
    client = _get_client()
    results = client.search(query=q, collection_key=collection_key, tag=tag, limit=limit)
    return [_item_to_summary(r) for r in results]


@router.get("/items/{item_key}")
def get_item(item_key: str) -> dict[str, Any]:
    """Get full item detail."""
    from backend.zotero.exceptions import ZoteroItemNotFoundError

    client = _get_client()
    try:
        item = client.get_item(item_key)
    except ZoteroItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _item_to_detail(item)


@router.get("/items/{item_key}/annotations")
def get_annotations(item_key: str) -> list[dict[str, Any]]:
    """Get annotations for an item."""
    from backend.zotero.exceptions import ZoteroItemNotFoundError

    client = _get_client()
    try:
        annotations = client.get_annotations(item_key)
    except ZoteroItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return annotations


@router.get("/collections")
def list_collections(
    parent_key: Optional[str] = Query(None, description="Parent collection key (null=root)"),
) -> list[dict[str, Any]]:
    """List collections (top-level or children of a parent)."""
    client = _get_client()
    results = client.list_collections(parent_key=parent_key)
    return results


@router.post("/path")
def set_db_path(path: str = Query(..., description="Path to zotero.sqlite")) -> dict[str, Any]:
    """Persist a custom Zotero DB path to settings_repo.

    Clears the cached client so the next request re-initializes with the new path.
    """
    global _client, _client_db_path
    _client = None
    _client_db_path = None

    try:
        from backend.services.settings_repo import SettingsRepo

        repo = SettingsRepo()
        repo.set("zotero_db_path", path)
    except Exception as exc:
        logger.warning("Could not persist zotero_db_path: %s", exc)

    return {"ok": True, "db_path": path}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item_to_summary(row: dict[str, Any]) -> dict[str, Any]:
    """Map a ZoteroClient.search() result to a summary dict."""
    return {
        "key": row.get("key", ""),
        "title": row.get("title", ""),
        "item_type": row.get("item_type", ""),
        "year": row.get("year"),
        "authors": row.get("authors", []),
        "abstract": row.get("abstract"),
        "collections": row.get("collections", []),
        "tags": row.get("tags", []),
        "date_added": row.get("date_added"),
    }


def _item_to_detail(row: dict[str, Any]) -> dict[str, Any]:
    """Map a ZoteroClient.get_item() result to a detail dict."""
    return {
        "key": row.get("key", ""),
        "title": row.get("title", ""),
        "item_type": row.get("item_type", ""),
        "year": row.get("year"),
        "authors": row.get("authors", []),
        "abstract": row.get("abstract"),
        "collections": row.get("collections", []),
        "tags": row.get("tags", []),
        "date_added": row.get("date_added"),
        "date_modified": row.get("date_modified"),
        "extra": row.get("extra"),
        "doi": row.get("doi"),
        "url": row.get("url"),
        "attachments": row.get("attachments", []),
    }
