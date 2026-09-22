"""Read-only Zotero SQLite client.

Provides structured access to a Zotero local database without modifying it.
All connections use ``mode=ro`` (SQLite URI read-only) to coexist safely
with the Zotero application, which may hold the database open.

Typical usage::

    from backend.zotero import ZoteroClient

    client = ZoteroClient("/home/user/Zotero/zotero.sqlite")
    results = client.search("neural networks")
    item = client.get_item("ABCD1234")
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from backend.zotero.exceptions import (
    ZoteroCollectionNotFoundError,
    ZoteroDatabaseLockedError,
    ZoteroDatabaseNotFoundError,
    ZoteroItemNotFoundError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default search paths for the Zotero database
# ---------------------------------------------------------------------------

_DEFAULT_ZOTERO_DIRS: list[Path] = [
    # Linux
    Path.home() / "Zotero",
    # macOS
    Path.home() / "Zotero",
    # Windows: %APPDATA%/Zotero/Zotero  # noqa: ERA001
    Path(os.environ.get("APPDATA", "")) / "Zotero" / "Zotero",
]


def _default_db_paths() -> list[Path]:
    """Return candidate Zotero database paths (env var > defaults)."""
    env_path = os.environ.get("ZOTERO_DB_PATH")
    if env_path:
        return [Path(env_path).expanduser()]
    return [p / "zotero.sqlite" for p in _DEFAULT_ZOTERO_DIRS]


def _resolve_db_path(db_path: Path | None = None) -> Path:
    """Resolve and validate the database path.

    Priority: explicit argument > ZOTERO_DB_PATH env var > default locations.
    """
    if db_path is not None:
        path = Path(db_path).expanduser()
        if not path.exists():
            raise ZoteroDatabaseNotFoundError([str(path)])
        return path

    for candidate in _default_db_paths():
        if candidate.exists():
            return candidate

    raise ZoteroDatabaseNotFoundError([str(p) for p in _default_db_paths()])


# ---------------------------------------------------------------------------
# ZoteroClient
# ---------------------------------------------------------------------------


class ZoteroClient:
    """Read-only access to a Zotero SQLite database.

    Parameters
    ----------
    db_path:
        Explicit path to ``zotero.sqlite``. If ``None``, searches
        ``ZOTERO_DB_PATH`` env var then default locations.
    timeout:
        SQLite connection timeout in seconds (default 10). Raises
        :class:`ZoteroDatabaseLockedError` if the timeout elapses.
    """

    def __init__(self, db_path: Path | str | None = None, timeout: float = 10.0) -> None:
        self._resolved_path = _resolve_db_path(Path(db_path) if db_path else None)
        self._timeout = timeout

    @property
    def db_path(self) -> Path:
        return self._resolved_path

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    @contextmanager
    def _connect(self) -> sqlite3.Connection:
        """Open a read-only SQLite connection.

        Uses ``?mode=ro`` URI to avoid interfering with Zotero's own locks.
        """
        uri = f"file:{self._resolved_path}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=self._timeout)
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if "locked" in msg or "unable to open" in msg:
                raise ZoteroDatabaseLockedError(str(self._resolved_path)) from exc
            raise
        try:
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            conn.close()

    def _execute(self, query: str, params: tuple | tuple[()] = ()) -> list[sqlite3.Row]:
        """Execute a query and return all rows."""
        with self._connect() as conn:
            cursor = conn.execute(query, params)
            return cursor.fetchall()

    def _execute_one(self, query: str, params: tuple) -> sqlite3.Row | None:
        """Execute a query and return at most one row."""
        with self._connect() as conn:
            cursor = conn.execute(query, params)
            return cursor.fetchone()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """Check if the database is accessible and return basic stats."""
        try:
            row = self._execute_one(
                "SELECT COUNT(*) as cnt FROM items WHERE itemTypeID NOT IN (14, 15, 16)",
                (),
            )
            item_count = row["cnt"] if row else 0
            return {
                "status": "ok",
                "db_path": str(self._resolved_path),
                "item_count": item_count,
            }
        except Exception as exc:
            return {
                "status": "error",
                "db_path": str(self._resolved_path),
                "error": str(exc),
            }

    def get_stats(self) -> dict[str, Any]:
        """Return statistics about the library."""
        item_count = self._execute_one(
            "SELECT COUNT(*) as cnt FROM items WHERE itemTypeID NOT IN (14, 15, 16)",
            (),
        )
        collection_count = self._execute_one(
            "SELECT COUNT(*) as cnt FROM collections", ()
        )
        tag_count = self._execute_one(
            "SELECT COUNT(*) as cnt FROM tags", ()
        )
        attachment_count = self._execute_one(
            "SELECT COUNT(*) as cnt FROM itemAttachments WHERE linkMode != 3", ()
        )
        return {
            "items": item_count["cnt"] if item_count else 0,
            "collections": collection_count["cnt"] if collection_count else 0,
            "tags": tag_count["cnt"] if tag_count else 0,
            "attachments": attachment_count["cnt"] if attachment_count else 0,
        }

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        collection_key: str | None = None,
        tag: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search items by title, abstract, and author name.

        Parameters
        ----------
        query:
            Text to match (case-insensitive LIKE).
        collection_key:
            Optional collection key to restrict results.
        tag:
            Optional tag name to filter.
        limit:
            Maximum number of results.
        """
        like_pattern = f"%{query}%"
        rows = self._execute(
            """
            SELECT DISTINCT
                i.itemID,
                i.key,
                it.typeName AS item_type,
                COALESCE(
                    (SELECT idv.value FROM itemData id
                     JOIN fields f ON id.fieldID = f.fieldID
                     JOIN itemDataValues idv ON id.valueID = idv.valueID
                     WHERE id.itemID = i.itemID AND f.fieldName = 'title'
                     LIMIT 1),
                    ''
                ) AS title,
                COALESCE(
                    (SELECT idv.value FROM itemData id
                     JOIN fields f ON id.fieldID = f.fieldID
                     JOIN itemDataValues idv ON id.valueID = idv.valueID
                     WHERE id.itemID = i.itemID AND f.fieldName = 'date'
                     LIMIT 1),
                    ''
                ) AS date,
                COALESCE(
                    (SELECT idv.value FROM itemData id
                     JOIN fields f ON id.fieldID = f.fieldID
                     JOIN itemDataValues idv ON id.valueID = idv.valueID
                     WHERE id.itemID = i.itemID AND f.fieldName = 'abstractNote'
                     LIMIT 1),
                    ''
                ) AS abstract,
                i.dateModified
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            WHERE i.itemID IN (
                -- Title or abstract match
                SELECT DISTINCT id.itemID
                FROM itemData id
                JOIN itemDataValues idv ON id.valueID = idv.valueID
                JOIN fields f ON id.fieldID = f.fieldID
                WHERE f.fieldName IN ('title', 'abstractNote')
                  AND idv.value LIKE ?
            )
            OR i.itemID IN (
                -- Author name match
                SELECT DISTINCT ic.itemID
                FROM itemCreators ic
                JOIN creators c ON ic.creatorID = c.creatorID
                WHERE c.firstName LIKE ?
                   OR c.lastName LIKE ?
            )
            ORDER BY i.dateModified DESC
            LIMIT ?
            """,
            (like_pattern, like_pattern, like_pattern, limit),
        )

        results = [self._row_to_summary(row) for row in rows]

        # Post-filter by collection if specified
        if collection_key:
            collection_ids = self._collection_item_ids(collection_key)
            results = [r for r in results if r["itemID"] in collection_ids]

        # Post-filter by tag if specified
        if tag:
            tag_item_ids = self._tag_item_ids(tag)
            results = [r for r in results if r["itemID"] in tag_item_ids]

        return results

    # ------------------------------------------------------------------
    # Item retrieval
    # ------------------------------------------------------------------

    def get_item(self, item_key: str) -> dict[str, Any]:
        """Retrieve full metadata for a single item.

        Returns a dict with: key, type, title, date, abstract, authors,
        tags, collections, attachments, notes, DOI, URL, and all other
        type-specific fields.
        """
        row = self._execute_one(
            """
            SELECT i.itemID, i.key, it.typeName, i.dateModified
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            WHERE i.key = ? AND i.itemTypeID != 0
            """,
            (item_key,),
        )
        if row is None:
            raise ZoteroItemNotFoundError(item_key)

        item_id = row["itemID"]

        # Fetch all type-specific fields
        field_rows = self._execute(
            """
            SELECT f.fieldName, idv.value
            FROM itemData id
            JOIN fields f ON id.fieldID = f.fieldID
            JOIN itemDataValues idv ON id.valueID = idv.valueID
            WHERE id.itemID = ?
            """,
            (item_id,),
        )
        fields: dict[str, str] = {r["fieldName"]: r["value"] for r in field_rows}

        # Fetch creators
        creator_rows = self._execute(
            """
            SELECT c.firstName, c.lastName, ct.creatorType
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
            """,
            (item_id,),
        )
        authors = [
            {
                "firstName": r["firstName"],
                "lastName": r["lastName"],
                "creatorType": r["creatorType"],
            }
            for r in creator_rows
        ]

        # Fetch tags
        tag_rows = self._execute(
            """
            SELECT t.name, it.type
            FROM itemTags it
            JOIN tags t ON it.tagID = t.tagID
            WHERE it.itemID = ?
            """,
            (item_id,),
        )
        tags = [{"name": r["name"], "type": r["type"]} for r in tag_rows]

        # Fetch collection membership
        collection_rows = self._execute(
            """
            SELECT c.key, c.collectionName
            FROM collectionItems ci
            JOIN collections c ON ci.collectionID = c.collectionID
            WHERE ci.itemID = ?
            """,
            (item_id,),
        )
        collections = [
            {"key": r["key"], "name": r["collectionName"]} for r in collection_rows
        ]

        # Fetch child attachments
        attachment_rows = self._execute(
            """
            SELECT ia.itemID, ia.contentType, ia.path, ia.linkMode
            FROM itemAttachments ia
            WHERE ia.parentItemID = ?
            """,
            (item_id,),
        )
        attachments = [
            {
                "itemID": r["itemID"],
                "contentType": r["contentType"],
                "path": r["path"],
                "linkMode": r["linkMode"],
            }
            for r in attachment_rows
        ]

        # Fetch child notes
        note_rows = self._execute(
            """
            SELECT n.note, n.title
            FROM itemNotes n
            WHERE n.parentItemID = ?
            """,
            (item_id,),
        )
        notes = [{"title": r["title"], "note": r["note"]} for r in note_rows]

        return {
            "key": row["key"],
            "item_type": row["typeName"],
            "dateModified": row["dateModified"],
            "title": fields.get("title", ""),
            "date": fields.get("date", ""),
            "abstract": fields.get("abstractNote", ""),
            "doi": fields.get("DOI", ""),
            "url": fields.get("url", ""),
            "authors": authors,
            "tags": tags,
            "collections": collections,
            "attachments": attachments,
            "notes": notes,
            "fields": fields,
        }

    # ------------------------------------------------------------------
    # Annotations
    # ------------------------------------------------------------------

    def get_annotations(self, item_key: str) -> list[dict[str, Any]]:
        """Retrieve PDF annotations (highlights, notes, underlines) for an item.

        Zotero stores annotations as child items with ``itemAnnotation`` type.
        """
        parent = self.get_item(item_key)

        # Annotation items are children of the attachment, not the parent item.
        # We need to find attachment children first, then their annotations.
        attachment_ids = [a["itemID"] for a in parent["attachments"]]
        if not attachment_ids:
            return []

        # Get annotation type ID
        anno_type_row = self._execute_one(
            "SELECT itemTypeID FROM itemTypes WHERE typeName = 'annotation'", ()
        )
        if anno_type_row is None:
            return []
        anno_type_id = anno_type_row["itemTypeID"]

        # Get annotations for all attachments
        placeholders = ",".join("?" * len(attachment_ids))
        rows = self._execute(
            f"""
            SELECT i.itemID, i.key, i.dateModified
            FROM items i
            WHERE i.parentItemID IN ({placeholders})
              AND i.itemTypeID = ?
            ORDER BY i.dateModified ASC
            """,
            (*attachment_ids, anno_type_id),
        )

        annotations: list[dict[str, Any]] = []
        for row in rows:
            anno_id = row["itemID"]
            # Annotation fields are stored in itemData
            field_rows = self._execute(
                """
                SELECT f.fieldName, idv.value
                FROM itemData id
                JOIN fields f ON id.fieldID = f.fieldID
                JOIN itemDataValues idv ON id.valueID = idv.valueID
                WHERE id.itemID = ?
                """,
                (anno_id,),
            )
            fields = {r["fieldName"]: r["value"] for r in field_rows}

            annotations.append(
                {
                    "key": row["key"],
                    "type": fields.get("annotationType", "note"),
                    "text": fields.get("annotationText", ""),
                    "comment": fields.get("annotationComment", ""),
                    "color": fields.get("annotationColor", ""),
                    "pageLabel": fields.get("annotationPageLabel", ""),
                    "sortIndex": fields.get("annotationSortIndex", ""),
                    "dateModified": row["dateModified"],
                }
            )

        return annotations

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    def list_collections(self, parent_key: str | None = None) -> list[dict[str, Any]]:
        """List collections (optionally filtered by parent collection).

        Returns a flat list with ``parentKey`` for tree reconstruction.
        """
        if parent_key is None:
            rows = self._execute(
                """
                SELECT c.collectionID, c.key, c.collectionName, c.parentCollectionID,
                       (SELECT pc.key FROM collections pc
                        WHERE pc.collectionID = c.parentCollectionID) AS parentKey,
                       (SELECT COUNT(*) FROM collectionItems ci
                        WHERE ci.collectionID = c.collectionID) AS itemCount
                FROM collections c
                WHERE c.parentCollectionID IS NULL
                ORDER BY c.collectionName
                """,
                (),
            )
        else:
            parent_id = self._collection_id_by_key(parent_key)
            rows = self._execute(
                """
                SELECT c.collectionID, c.key, c.collectionName, c.parentCollectionID,
                       (SELECT pc.key FROM collections pc
                        WHERE pc.collectionID = c.parentCollectionID) AS parentKey,
                       (SELECT COUNT(*) FROM collectionItems ci
                        WHERE ci.collectionID = c.collectionID) AS itemCount
                FROM collections c
                WHERE c.parentCollectionID = ?
                ORDER BY c.collectionName
                """,
                (parent_id,),
            )

        return [
            {
                "key": r["key"],
                "name": r["collectionName"],
                "parentKey": r["parentKey"],
                "itemCount": r["itemCount"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # PDF fulltext
    # ------------------------------------------------------------------

    def read_pdf_fulltext(
        self,
        item_key: str,
        chunk_offset: int = 0,
        chunk_size: int = 10000,
        max_chars: int = 50000,
    ) -> dict[str, Any]:
        """Read PDF full text for an item (user-invoked, not automatic).

        Strategy:
        1. Check Zotero's ``fulltextItems`` / ``fulltextItemWords`` index.
        2. If unavailable, locate the local PDF file for external extraction.

        Parameters
        ----------
        item_key:
            Zotero item key (parent item, not the attachment).
        chunk_offset:
            Character offset for chunked reading.
        chunk_size:
            Characters per chunk.
        max_chars:
            Maximum characters to return in one call.

        Returns
        -------
        dict with keys: item_key, total_chars, chunk_offset, chunk_text,
        has_more, source (index|file|unavailable).
        """
        item_id = self._item_id_by_key(item_key)

        # Strategy 1: Check if Zotero has indexed the fulltext
        index_text = self._get_fulltext_from_index(item_id)
        if index_text is not None:
            return self._chunk_text(item_key, index_text, chunk_offset, chunk_size, max_chars, "index")

        # Strategy 2: Locate the PDF file
        pdf_path = self._find_pdf_attachment(item_id)
        if pdf_path is not None and Path(pdf_path).exists():
            return {
                "item_key": item_key,
                "total_chars": -1,  # unknown until extraction
                "chunk_offset": chunk_offset,
                "chunk_text": "",
                "has_more": False,
                "source": "file",
                "attachment_path": pdf_path,
                "message": (
                    "PDF file found but full text not pre-indexed by Zotero. "
                    "Use the attachment_path with a PDF extraction tool."
                ),
            }

        return {
            "item_key": item_key,
            "total_chars": 0,
            "chunk_offset": chunk_offset,
            "chunk_text": "",
            "has_more": False,
            "source": "unavailable",
            "message": "No full text available (not indexed, no local PDF).",
        }

    # ------------------------------------------------------------------
    # BibTeX export
    # ------------------------------------------------------------------

    def get_bibtex(self, item_keys: list[str]) -> str:
        """Generate BibTeX entries for the given item keys.

        Produces output compatible with Sage's existing
        ``office_parse_bibtex`` tool.
        """
        entries: list[str] = []
        for key in item_keys:
            item = self.get_item(key)
            entry = self._item_to_bibtex(item)
            entries.append(entry)
        return "\n\n".join(entries)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _item_id_by_key(self, item_key: str) -> int:
        row = self._execute_one(
            "SELECT itemID FROM items WHERE key = ?", (item_key,)
        )
        if row is None:
            raise ZoteroItemNotFoundError(item_key)
        return row["itemID"]

    def _collection_id_by_key(self, collection_key: str) -> int:
        row = self._execute_one(
            "SELECT collectionID FROM collections WHERE key = ?", (collection_key,)
        )
        if row is None:
            raise ZoteroCollectionNotFoundError(collection_key)
        return row["collectionID"]

    def _collection_item_ids(self, collection_key: str) -> set[int]:
        collection_id = self._collection_id_by_key(collection_key)
        rows = self._execute(
            "SELECT itemID FROM collectionItems WHERE collectionID = ?",
            (collection_id,),
        )
        return {r["itemID"] for r in rows}

    def _tag_item_ids(self, tag_name: str) -> set[int]:
        rows = self._execute(
            """
            SELECT it.itemID
            FROM itemTags it
            JOIN tags t ON it.tagID = t.tagID
            WHERE t.name = ?
            """,
            (tag_name,),
        )
        return {r["itemID"] for r in rows}

    def _row_to_summary(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a search result row to a summary dict."""
        # Fetch authors for this item
        author_rows = self._execute(
            """
            SELECT c.firstName, c.lastName
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
            """,
            (row["itemID"],),
        )
        authors = ", ".join(f"{r['lastName']} {r['firstName']}" for r in author_rows)

        # Fetch tags
        tag_rows = self._execute(
            """
            SELECT t.name FROM itemTags it
            JOIN tags t ON it.tagID = t.tagID
            WHERE it.itemID = ?
            """,
            (row["itemID"],),
        )
        tags = [r["name"] for r in tag_rows]

        return {
            "itemID": row["itemID"],
            "key": row["key"],
            "item_type": row["item_type"],
            "title": row["title"],
            "date": row["date"],
            "abstract": row["abstract"],
            "authors": authors,
            "tags": tags,
            "dateModified": row["dateModified"],
        }

    def _get_fulltext_from_index(self, item_id: int) -> str | None:
        """Retrieve full text from Zotero's FTS index, if available."""
        # Zotero stores full text in a separate table (varies by version).
        # Try common schemas.
        for table in ("fulltextItemWords", "fulltextItems"):
            try:
                self._execute(f"SELECT 1 FROM {table} LIMIT 1")
            except sqlite3.OperationalError:
                continue

        # Primary: fulltextItemWords joined with fulltextWords
        try:
            rows = self._execute(
                """
                SELECT fw.word
                FROM fulltextItemWords fiw
                JOIN fulltextWords fw ON fiw.wordID = fw.wordID
                WHERE fiw.itemID = ?
                ORDER BY fiw.wordID
                """,
                (item_id,),
            )
            if rows:
                return " ".join(r["word"] for r in rows)
        except sqlite3.OperationalError:
            pass

        return None

    def _find_pdf_attachment(self, item_id: int) -> str | None:
        """Find the local PDF file path for an item (via child attachments)."""
        rows = self._execute(
            """
            SELECT ia.path, ia.contentType
            FROM itemAttachments ia
            WHERE ia.parentItemID = ?
              AND ia.contentType = 'application/pdf'
            LIMIT 1
            """,
            (item_id,),
        )
        if not rows:
            return None

        raw_path = rows[0]["path"]
        # Zotero uses 'storage:' prefix for bundled files
        if raw_path.startswith("storage:"):
            relative = raw_path[len("storage:"):]
            zotero_data_dir = self._resolved_path.parent
            candidate = zotero_data_dir / "storage" / relative
            return str(candidate) if candidate.exists() else None

        return raw_path if Path(raw_path).exists() else None

    def _chunk_text(
        self,
        item_key: str,
        text: str,
        chunk_offset: int,
        chunk_size: int,
        max_chars: int,
        source: str,
    ) -> dict[str, Any]:
        total_chars = len(text)
        end = min(chunk_offset + max_chars, total_chars)
        chunk = text[chunk_offset:end]
        return {
            "item_key": item_key,
            "total_chars": total_chars,
            "chunk_offset": chunk_offset,
            "chunk_text": chunk,
            "has_more": end < total_chars,
            "source": source,
        }

    def _item_to_bibtex(self, item: dict[str, Any]) -> str:
        """Convert a Zotero item dict to a BibTeX entry string."""
        item_type = item["item_type"]
        bibtex_type = self._zotero_type_to_bibtex(item_type)
        key = item["key"]

        # Build author string
        authors = item.get("authors", [])
        author_str = " and ".join(
            f"{a['lastName']}, {a['firstName']}" for a in authors
        )

        fields = item.get("fields", {})
        lines = [f"@{bibtex_type}{{{key},"]

        field_map = [
            ("title", fields.get("title", "")),
            ("author", author_str),
            ("year", (fields.get("date", "") or "")[:4]),
            ("journal", fields.get("publicationTitle", "")),
            ("volume", fields.get("volume", "")),
            ("number", fields.get("issue", "")),
            ("pages", fields.get("pages", "")),
            ("doi", fields.get("DOI", "")),
            ("url", fields.get("url", "")),
            ("abstract", fields.get("abstractNote", "")),
            ("publisher", fields.get("publisher", "")),
            ("address", fields.get("place", "")),
        ]

        for name, value in field_map:
            if value:
                escaped = value.replace("&", r"\&").replace("%", r"\%")
                lines.append(f"  {name} = {{{escaped}}},")

        lines.append("}")
        return "\n".join(lines)

    @staticmethod
    def _zotero_type_to_bibtex(zotero_type: str) -> str:
        """Map Zotero item type names to BibTeX entry types."""
        mapping = {
            "journalArticle": "article",
            "book": "book",
            "bookSection": "inbook",
            "conferencePaper": "inproceedings",
            "thesis": "phdthesis",
            "report": "techreport",
            "webpage": "misc",
            "patent": "misc",
            "presentation": "misc",
            "manuscript": "unpublished",
        }
        return mapping.get(zotero_type, "misc")
