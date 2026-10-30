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
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["zotero"])

# Lazy singleton — instantiated on first request to avoid startup cost when
# Zotero is not used. Re-created when db_path changes (see /path POST).
_client: Optional[Any] = None
_client_db_path: Optional[str] = None


def _get_configured_db_path() -> Optional[str]:
    """Return the user-configured Zotero DB path, if any.

    r94 修复后本函数与 MCP 侧曾各写一份解析逻辑（settings_repo → env），
    2026-10-27 起统一收敛到 ``backend.zotero.paths.resolve_zotero_db_path``，
    避免 UI 与 MCP 子进程读到不同的库。保留本包装函数是因为测试与调用
    点均按此名导入，且空字符串需转成 ``None`` 以维持「未配置」语义。
    """
    from backend.zotero.paths import resolve_zotero_db_path

    return resolve_zotero_db_path() or None


def _get_client(db_path_override: Optional[str] = None) -> Any:
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
#   key, name, parent_key, item_count, version
#
# GET /zotero/items/{key}/annotations — list of:
#   key, type, text, comment, color, page_label, date_added
#
# Dates: ISO 8601 UTC (Zotero SQLite dateAdded format).
# ---------------------------------------------------------------------------


@router.get("/status")
def get_status() -> Dict[str, Any]:
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
) -> List[Dict[str, Any]]:
    """Search library items."""
    client = _get_client()
    results = client.search(query=q, collection_key=collection_key, tag=tag, limit=limit)
    return [_item_to_summary(r) for r in results]


@router.get("/items/{item_key}")
def get_item(item_key: str) -> Dict[str, Any]:
    """Get full item detail."""
    from backend.zotero.exceptions import ZoteroItemNotFoundError

    client = _get_client()
    try:
        item = client.get_item(item_key)
    except ZoteroItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _item_to_detail(item)


@router.get("/items/{item_key}/annotations")
def get_annotations(item_key: str) -> List[Dict[str, Any]]:
    """Get annotations for an item."""
    from backend.zotero.exceptions import ZoteroItemNotFoundError

    client = _get_client()
    try:
        annotations = client.get_annotations(item_key)
    except ZoteroItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_annotation_to_rest(a) for a in annotations]


@router.get("/collections")
def list_collections(
    parent_key: Optional[str] = Query(None, description="Parent collection key (null=root)"),
) -> List[Dict[str, Any]]:
    """List collections (top-level or children of a parent)."""
    client = _get_client()
    return [_collection_to_rest(r) for r in client.list_collections(parent_key=parent_key)]


@router.post("/path")
def set_db_path(path: str = Query(..., description="Path to zotero.sqlite")) -> Dict[str, Any]:
    """Persist a custom Zotero DB path to settings_repo.

    Clears the cached client so the next request re-initializes with the new path.
    """
    global _client, _client_db_path
    _client = None
    _client_db_path = None

    try:
        # r94 修复: 同 _get_configured_db_path —— 模块与类名纠正后才能真正落库
        from backend.data.settings_repo import SettingsRepository

        repo = SettingsRepository()
        repo.set("zotero_db_path", path)
    except Exception as exc:
        logger.warning("Could not persist zotero_db_path: %s", exc)

    return {"ok": True, "db_path": path}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item_to_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map a ZoteroClient.search() result to a summary dict."""
    raw_year = row.get("year")
    return {
        "key": row.get("key", ""),
        "title": row.get("title", ""),
        "item_type": row.get("item_type", ""),
        "year": raw_year if isinstance(raw_year, int) else _year_from_date(row.get("date")),
        "authors": _author_names(row.get("authors")),
        "abstract": row.get("abstract"),
        "collections": _collection_names(row.get("collections")),
        "tags": _tag_names(row.get("tags")),
        "date_added": row.get("date_added"),
    }


def _item_to_detail(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map a ZoteroClient.get_item() result to a detail dict."""
    raw_year = row.get("year")
    return {
        "key": row.get("key", ""),
        "title": row.get("title", ""),
        "item_type": row.get("item_type", ""),
        "year": raw_year if isinstance(raw_year, int) else _year_from_date(row.get("date")),
        "authors": _author_names(row.get("authors")),
        "abstract": row.get("abstract"),
        "collections": _collection_names(row.get("collections")),
        "tags": _tag_names(row.get("tags")),
        "date_added": row.get("date_added"),
        "date_modified": row.get("date_modified") or row.get("dateModified"),
        "extra": row.get("extra"),
        "doi": row.get("doi"),
        "url": row.get("url"),
        "attachments": [_attachment_to_rest(a) for a in row.get("attachments") or []],
    }


# ---------------------------------------------------------------------------
# Client shape → REST shape normalization
#
# ``ZoteroClient`` predates this REST layer and returns a mix of shapes:
# joined author strings, ``[{name,type}]`` tags, ``parentKey/itemCount``
# collections, ``pageLabel`` annotations. The REST contract documented at the
# top of this file is snake_case with scalar lists; normalize here so the
# MCP-facing client API stays untouched.
# ---------------------------------------------------------------------------


def _year_from_date(value: Any) -> Optional[int]:
    if value is None:
        return None
    match = re.match(r"^\s*(\d{4})", str(value))
    return int(match.group(1)) if match else None


def _author_name(entry: Any) -> str:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        parts = [entry.get("firstName"), entry.get("lastName")]
        return " ".join(str(p).strip() for p in parts if p and str(p).strip())
    return ""


def _author_names(value: Any) -> List[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [name for name in (_author_name(item) for item in value) if name]
    return []


def _tag_names(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    names: List[str] = []
    for item in value:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name") or ""
        else:
            name = ""
        if str(name).strip():
            names.append(str(name).strip())
    return names


def _collection_names(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    names: List[str] = []
    for item in value:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name") or item.get("key") or ""
        else:
            name = ""
        if str(name).strip():
            names.append(str(name).strip())
    return names


def _attachment_to_rest(entry: Dict[str, Any]) -> Dict[str, Any]:
    path = entry.get("path") or ""
    filename = entry.get("filename") or ""
    if not filename and path:
        filename = path[len("storage:") :] if path.startswith("storage:") else Path(path).name
    return {
        "key": entry.get("key") or "",
        "filename": filename,
        "path": path or None,
        "content_type": entry.get("content_type") or entry.get("contentType") or None,
    }


def _annotation_to_rest(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "key": row.get("key", ""),
        "type": row.get("type", ""),
        "text": row.get("text") or None,
        "comment": row.get("comment") or None,
        "color": row.get("color") or None,
        "page_label": row.get("page_label") or row.get("pageLabel") or None,
        "date_added": row.get("date_added") or row.get("dateModified") or None,
    }


def _collection_to_rest(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "key": row.get("key", ""),
        "name": row.get("name", ""),
        "parent_key": row.get("parent_key", row.get("parentKey")),
        "item_count": row.get("item_count", row.get("itemCount", 0)),
        "version": row.get("version", 0),
    }
