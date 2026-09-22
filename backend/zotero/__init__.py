"""Zotero integration — read-only access to local Zotero SQLite database."""

from backend.zotero.client import ZoteroClient
from backend.zotero.exceptions import (
    ZoteroAttachmentNotFoundError,
    ZoteroCollectionNotFoundError,
    ZoteroDatabaseLockedError,
    ZoteroDatabaseNotFoundError,
    ZoteroError,
    ZoteroItemNotFoundError,
)

__all__ = [
    "ZoteroClient",
    "ZoteroError",
    "ZoteroDatabaseNotFoundError",
    "ZoteroDatabaseLockedError",
    "ZoteroItemNotFoundError",
    "ZoteroCollectionNotFoundError",
    "ZoteroAttachmentNotFoundError",
]
