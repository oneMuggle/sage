"""Zotero integration exceptions."""

from __future__ import annotations


class ZoteroError(Exception):
    """Base exception for all Zotero operations."""


class ZoteroDatabaseNotFoundError(ZoteroError):
    """Raised when the Zotero SQLite database cannot be located."""

    def __init__(self, searched_paths: list[str]):
        self.searched_paths = searched_paths
        paths_str = ", ".join(str(p) for p in searched_paths)
        super().__init__(
            f"Zotero database not found. Searched: {paths_str}. "
            "Set ZOTERO_DB_PATH env var or configure in Sage Settings."
        )


class ZoteroDatabaseLockedError(ZoteroError):
    """Raised when the Zotero database is exclusively locked by another process."""

    def __init__(self, db_path: str):
        super().__init__(
            f"Zotero database is locked by another process: {db_path}. "
            "Zotero may be running with exclusive locking mode."
        )


class ZoteroItemNotFoundError(ZoteroError):
    """Raised when a requested Zotero item does not exist."""

    def __init__(self, item_key: str):
        super().__init__(f"Zotero item not found: {item_key}")


class ZoteroCollectionNotFoundError(ZoteroError):
    """Raised when a requested collection does not exist."""

    def __init__(self, collection_key: str):
        super().__init__(f"Zotero collection not found: {collection_key}")


class ZoteroAttachmentNotFoundError(ZoteroError):
    """Raised when a requested attachment file does not exist."""

    def __init__(self, item_key: str, path: str | None = None):
        detail = f" at {path}" if path else ""
        super().__init__(f"Attachment not found for item {item_key}{detail}")
