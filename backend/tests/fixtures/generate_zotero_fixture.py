"""Generate a synthetic Zotero SQLite fixture for unit tests.

Creates a small but representative database at
``backend/tests/fixtures/zotero.sqlite`` with the schema tables that
:mod:`backend.zotero.client` reads: items, itemData, itemDataValues,
fields, itemTypes, creators, itemCreators, creatorTypes, tags, itemTags,
collections, collectionItems, itemAttachments, itemNotes, fulltextItems,
fulltextWords, fulltextItemWords.

Run::

    python -m backend.tests.fixtures.generate_zotero_fixture

The fixture file is committed alongside this script so tests are
deterministic and don't require re-generation on every run.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

FIXTURE_PATH = Path(__file__).resolve().parent / "zotero.sqlite"

# Synthetic ISO 8601 timestamps for all dateModified fields.
_NOW = "2026-09-22 10:00:00"


SCHEMA = """
CREATE TABLE itemTypes (
    itemTypeID INTEGER PRIMARY KEY,
    typeName TEXT NOT NULL
);

CREATE TABLE fields (
    fieldID INTEGER PRIMARY KEY,
    fieldName TEXT NOT NULL
);

CREATE TABLE creatorTypes (
    creatorTypeID INTEGER PRIMARY KEY,
    creatorType TEXT NOT NULL
);

CREATE TABLE items (
    itemID INTEGER PRIMARY KEY,
    itemTypeID INTEGER NOT NULL,
    key TEXT NOT NULL UNIQUE,
    dateModified TEXT NOT NULL,
    clientDateModified TEXT,
    libraryID INTEGER,
    parentItemID INTEGER
);

CREATE TABLE itemData (
    itemID INTEGER NOT NULL,
    fieldID INTEGER NOT NULL,
    valueID INTEGER NOT NULL,
    PRIMARY KEY (itemID, fieldID)
);

CREATE TABLE itemDataValues (
    valueID INTEGER PRIMARY KEY,
    value TEXT
);

CREATE TABLE creators (
    creatorID INTEGER PRIMARY KEY,
    firstName TEXT,
    lastName TEXT,
    fieldMode INTEGER DEFAULT 0
);

CREATE TABLE itemCreators (
    itemID INTEGER NOT NULL,
    creatorID INTEGER NOT NULL,
    creatorTypeID INTEGER NOT NULL,
    orderIndex INTEGER DEFAULT 0,
    PRIMARY KEY (itemID, creatorTypeID, orderIndex)
);

CREATE TABLE tags (
    tagID INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type INTEGER DEFAULT 0
);

CREATE TABLE itemTags (
    itemID INTEGER NOT NULL,
    tagID INTEGER NOT NULL,
    type INTEGER DEFAULT 0,
    PRIMARY KEY (itemID, tagID)
);

CREATE TABLE collections (
    collectionID INTEGER PRIMARY KEY,
    collectionName TEXT NOT NULL,
    parentCollectionID INTEGER,
    key TEXT NOT NULL UNIQUE,
    clientDateModified TEXT,
    dateModified TEXT
);

CREATE TABLE collectionItems (
    collectionID INTEGER NOT NULL,
    itemID INTEGER NOT NULL,
    orderIndex INTEGER DEFAULT 0,
    PRIMARY KEY (collectionID, itemID)
);

CREATE TABLE itemAttachments (
    itemID INTEGER PRIMARY KEY,
    parentItemID INTEGER,
    linkMode INTEGER,
    contentType TEXT,
    path TEXT,
    dateModified TEXT
);

CREATE TABLE itemNotes (
    itemID INTEGER PRIMARY KEY,
    parentItemID INTEGER,
    note TEXT,
    title TEXT,
    dateModified TEXT
);

CREATE TABLE fulltextItems (
    itemID INTEGER PRIMARY KEY,
    version INTEGER,
    indexedPages INTEGER,
    indexedChars INTEGER
);

CREATE TABLE fulltextWords (
    wordID INTEGER PRIMARY KEY,
    word TEXT NOT NULL
);

CREATE TABLE fulltextItemWords (
    wordID INTEGER NOT NULL,
    itemID INTEGER NOT NULL,
    PRIMARY KEY (wordID, itemID)
);

CREATE INDEX idx_items_key ON items(key);
CREATE INDEX idx_itemData_item ON itemData(itemID);
CREATE INDEX idx_itemCreators_item ON itemCreators(itemID);
CREATE INDEX idx_itemTags_item ON itemTags(itemID);
"""


_ITEM_TYPES = [
    (1, "journalArticle"),
    (2, "book"),
    (3, "conferencePaper"),
    (4, "thesis"),
    (14, "attachment"),
    (15, "note"),
    (16, "annotation"),
]

_FIELDS = [
    (1, "title"),
    (2, "date"),
    (3, "abstractNote"),
    (4, "publicationTitle"),
    (5, "DOI"),
    (6, "url"),
    (7, "volume"),
    (8, "issue"),
    (9, "pages"),
    (10, "publisher"),
    (11, "place"),
    # Annotation-specific fields:
    (101, "annotationType"),
    (102, "annotationText"),
    (103, "annotationComment"),
    (104, "annotationColor"),
    (105, "annotationPageLabel"),
    (106, "annotationSortIndex"),
]


_CREATOR_TYPES = [
    (1, "author"),
    (2, "editor"),
    (3, "translator"),
]


_ITEMS = [
    # Tuple shape: (itemID, itemTypeID, key, dateModified, parentItemID)
    (1, 1, "ABCD1234", _NOW, None),
    (2, 1, "EFGH5678", _NOW, None),
    (3, 2, "BOOK0001", _NOW, None),
    (4, 3, "CONF0001", _NOW, None),
    (5, 4, "THES0001", _NOW, None),
    # Attachments (linkMode=0 = imported file in storage):
    (10, 14, "ATT00001", _NOW, 1),
    (11, 14, "ATT00002", _NOW, 2),
    (12, 14, "ATT00003", _NOW, 3),
    # Notes:
    (20, 15, "NOTE0001", _NOW, 1),
    # Annotations on attachments:
    (30, 16, "ANN00001", _NOW, 10),
    (31, 16, "ANN00002", _NOW, 10),
    (32, 16, "ANN00003", _NOW, 11),
]


# Field values referenced by itemData (iid, fieldID, value)
_ITEM_DATA = [
    # Item 1: journalArticle "Neural Network Survey"
    (1, 1, "Neural Network Survey Paper"),
    (1, 2, "2024"),
    (1, 3, "A comprehensive survey of neural network architectures and training methods."),
    (1, 4, "Journal of ML Research"),
    (1, 5, "10.1234/jmlr.2024.001"),
    (1, 7, "12"),
    (1, 8, "3"),
    (1, 9, "45-67"),
    # Item 2: journalArticle "Transformer Models"
    (2, 1, "Transformer Models for NLP"),
    (2, 2, "2023"),
    (2, 3, "An analysis of transformer architectures for natural language understanding."),
    (2, 4, "ACL Conference"),
    (2, 5, "10.1234/acl.2023.042"),
    # Item 3: book "Deep Learning Foundations"
    (3, 1, "Deep Learning Foundations"),
    (3, 2, "2022"),
    (3, 10, "MIT Press"),
    (3, 11, "Cambridge, MA"),
    # Item 4: conferencePaper "On Optimization"
    (4, 1, "On Optimization for Large Models"),
    (4, 2, "2024"),
    (4, 4, "NeurIPS"),
    (4, 9, "1001-1015"),
    # Item 5: thesis "Bayesian Approaches"
    (5, 1, "Bayesian Approaches in Computer Vision"),
    (5, 2, "2023"),
    (5, 10, "Stanford University"),
    # Annotation 30 (highlight on attachment 10):
    (30, 101, "highlight"),
    (30, 102, "neural networks achieve state of the art"),
    (30, 103, "Key result"),
    (30, 104, "#ff0000"),
    (30, 105, "3"),
    # Annotation 31 (underline on attachment 10):
    (31, 101, "underline"),
    (31, 102, "transformer architectures"),
    # Annotation 32 (note on attachment 11):
    (32, 101, "note"),
    (32, 102, "Bayesian methods are introduced here"),
]


_NOTES = [
    # (itemID, parentItemID, note HTML, title)
    (20, 1, "<p>Important finding on p. 5.</p>", "My Note on Neural Survey"),
]


_CREATORS = [
    (1, "Jane", "Doe"),
    (2, "John", "Smith"),
    (3, "Alice", "Johnson"),
    (4, "Bob", "Williams"),
    (5, "Carol", "Brown"),
]


_ITEM_CREATORS = [
    # Tuple shape: (itemID, creatorID, creatorTypeID, orderIndex)
    (1, 1, 1, 0),
    (1, 2, 1, 1),
    (2, 3, 1, 0),
    (3, 1, 1, 0),
    (3, 4, 2, 1),
    (4, 2, 1, 0),
    (4, 5, 1, 1),
    (5, 3, 1, 0),
]


_TAGS = [
    (1, "machine-learning"),
    (2, "neural-networks"),
    (3, "nlp"),
]


_ITEM_TAGS = [
    (1, 1),
    (1, 2),
    (2, 1),
    (2, 3),
    (3, 2),
    (4, 1),
    (5, 1),
]


_COLLECTIONS = [
    # Tuple shape: (collectionID, key, name, parentCollectionID)
    (1, "COLL001", "NLP Papers", None),
    (2, "COLL002", "Machine Learning", None),
    (3, "COLL003", "Transformer Models", 1),
    (4, "COLL004", "Books", None),
    (5, "COLL005", "Textbooks", 4),
]


_COLLECTION_ITEMS = [
    # Tuple shape: (collectionID, itemID, orderIndex)
    (1, 1, 0),
    (1, 2, 1),
    (2, 1, 0),
    (2, 3, 1),
    (3, 2, 0),
    (4, 3, 0),
    (5, 3, 0),
]


_ITEM_ATTACHMENTS = [
    # Tuple shape: (itemID, parentItemID, linkMode, contentType, path)
    (10, 1, 0, "application/pdf", "storage:ABCD1234.pdf"),
    (11, 2, 0, "application/pdf", "storage:EFGH5678.pdf"),
    (12, 3, 0, "application/pdf", "storage:BOOK0001.pdf"),
]


_FULLTEXT_ITEMS = [
    (1, 5, 12, 50000),
    (2, 5, 8, 30000),
]


_FULLTEXT_WORDS = [
    (1, "neural"),
    (2, "network"),
    (3, "transformer"),
    (4, "attention"),
    (5, "model"),
]


_FULLTEXT_ITEM_WORDS = [
    (1, 1),
    (2, 1),
    (3, 2),
    (4, 2),
    (5, 1),
    (5, 2),
]


def build_fixture(path: Path = FIXTURE_PATH) -> Path:
    """Create the synthetic SQLite fixture at ``path``."""
    if path.exists():
        path.unlink()

    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)

        conn.executemany(
            "INSERT INTO itemTypes (itemTypeID, typeName) VALUES (?, ?)",
            _ITEM_TYPES,
        )
        conn.executemany(
            "INSERT INTO fields (fieldID, fieldName) VALUES (?, ?)",
            _FIELDS,
        )
        conn.executemany(
            "INSERT INTO creatorTypes (creatorTypeID, creatorType) VALUES (?, ?)",
            _CREATOR_TYPES,
        )
        conn.executemany(
            "INSERT INTO items (itemID, itemTypeID, key, dateModified, parentItemID) "
            "VALUES (?, ?, ?, ?, ?)",
            _ITEMS,
        )

        # Assign valueIDs and insert itemDataValues
        unique_values = sorted({row[2] for row in _ITEM_DATA})
        value_to_id: dict[str, int] = {}
        for value_id, value in enumerate(unique_values, start=1):
            conn.execute(
                "INSERT INTO itemDataValues (valueID, value) VALUES (?, ?)",
                (value_id, value),
            )
            value_to_id[value] = value_id

        conn.executemany(
            "INSERT INTO itemData (itemID, fieldID, valueID) VALUES (?, ?, ?)",
            [(iid, fid, value_to_id[val]) for iid, fid, val in _ITEM_DATA],
        )

        conn.executemany(
            "INSERT INTO creators (creatorID, firstName, lastName) VALUES (?, ?, ?)",
            _CREATORS,
        )
        conn.executemany(
            "INSERT INTO itemCreators (itemID, creatorID, creatorTypeID, orderIndex) "
            "VALUES (?, ?, ?, ?)",
            _ITEM_CREATORS,
        )

        conn.executemany(
            "INSERT INTO tags (tagID, name) VALUES (?, ?)",
            _TAGS,
        )
        conn.executemany(
            "INSERT INTO itemTags (itemID, tagID) VALUES (?, ?)",
            _ITEM_TAGS,
        )

        conn.executemany(
            "INSERT INTO collections (collectionID, key, collectionName, parentCollectionID) "
            "VALUES (?, ?, ?, ?)",
            _COLLECTIONS,
        )
        conn.executemany(
            "INSERT INTO collectionItems (collectionID, itemID, orderIndex) "
            "VALUES (?, ?, ?)",
            _COLLECTION_ITEMS,
        )

        conn.executemany(
            "INSERT INTO itemAttachments (itemID, parentItemID, linkMode, contentType, path) "
            "VALUES (?, ?, ?, ?, ?)",
            _ITEM_ATTACHMENTS,
        )
        conn.executemany(
            "INSERT INTO itemNotes (itemID, parentItemID, note, title, dateModified) "
            "VALUES (?, ?, ?, ?, ?)",
            [(iid, pid, note, title, _NOW) for iid, pid, note, title in _NOTES],
        )

        conn.executemany(
            "INSERT INTO fulltextItems (itemID, version, indexedPages, indexedChars) "
            "VALUES (?, ?, ?, ?)",
            _FULLTEXT_ITEMS,
        )
        conn.executemany(
            "INSERT INTO fulltextWords (wordID, word) VALUES (?, ?)",
            _FULLTEXT_WORDS,
        )
        conn.executemany(
            "INSERT INTO fulltextItemWords (wordID, itemID) VALUES (?, ?)",
            _FULLTEXT_ITEM_WORDS,
        )

        conn.commit()
    finally:
        conn.close()

    return path


if __name__ == "__main__":
    out = build_fixture()
    size = out.stat().st_size
    print(f"Wrote fixture: {out} ({size} bytes)")  # noqa: T201
