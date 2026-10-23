"""R181 — ZoteroClient（Zotero SQLite 只读客户端）单元测试。

用真实 tmp SQLite 文件按 Zotero schema 建最小库，覆盖：路径解析、
health/stats、search（标题/作者/集合/标签过滤/排序/limit）、get_item
（字段/作者/标签/集合/附件/笔记）、get_annotations、list_collections、
read_pdf_fulltext（索引分块 / storage 文件 / 绝对路径 / 不可用）、
get_bibtex（类型映射 / & % 转义）、连接异常映射（locked → 专属异常）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.zotero.client import ZoteroClient, _default_db_paths
from backend.zotero.exceptions import (
    ZoteroCollectionNotFoundError,
    ZoteroDatabaseLockedError,
    ZoteroDatabaseNotFoundError,
    ZoteroItemNotFoundError,
)

pytestmark = pytest.mark.unit


def _build_zotero_db(db_path: Path, storage_dir: Path, abs_pdf: Path) -> None:
    """按 Zotero 真实 schema 的最小子集建库（含 fulltext 索引表）。"""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE items (
            itemID INTEGER PRIMARY KEY,
            itemTypeID INTEGER NOT NULL,
            key TEXT UNIQUE NOT NULL,
            dateModified TEXT,
            parentItemID INTEGER
        );
        CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT NOT NULL);
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT NOT NULL);
        CREATE TABLE itemData (itemID INTEGER NOT NULL, fieldID INTEGER NOT NULL,
                               valueID INTEGER NOT NULL);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);
        CREATE TABLE creatorTypes (creatorTypeID INTEGER PRIMARY KEY, creatorType TEXT NOT NULL);
        CREATE TABLE itemCreators (itemID INTEGER NOT NULL, creatorID INTEGER NOT NULL,
                                   creatorTypeID INTEGER NOT NULL, orderIndex INTEGER DEFAULT 0);
        CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL,
                                  collectionName TEXT, parentCollectionID INTEGER);
        CREATE TABLE collectionItems (collectionID INTEGER NOT NULL, itemID INTEGER NOT NULL);
        CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE itemTags (itemID INTEGER NOT NULL, tagID INTEGER NOT NULL,
                               type INTEGER DEFAULT 0);
        CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INTEGER,
                                      linkMode INTEGER NOT NULL, contentType TEXT, path TEXT);
        CREATE TABLE itemNotes (itemID INTEGER PRIMARY KEY, parentItemID INTEGER,
                                note TEXT, title TEXT);
        CREATE TABLE fulltextWords (wordID INTEGER PRIMARY KEY, word TEXT NOT NULL);
        CREATE TABLE fulltextItemWords (itemID INTEGER NOT NULL, wordID INTEGER NOT NULL);
        """
    )
    # itemTypes：14=attachment / 15=annotation（health 统计排除 14/15/16）
    conn.executemany(
        "INSERT INTO itemTypes VALUES (?, ?)",
        [(1, "journalArticle"), (2, "book"), (14, "attachment"), (15, "annotation")],
    )
    conn.executemany(
        "INSERT INTO fields VALUES (?, ?)",
        [
            (1, "title"),
            (2, "date"),
            (3, "abstractNote"),
            (4, "DOI"),
            (5, "url"),
            (6, "publicationTitle"),
            (7, "pages"),
            (8, "annotationType"),
            (9, "annotationText"),
            (10, "annotationComment"),
            (11, "annotationColor"),
            (12, "annotationPageLabel"),
            (13, "annotationSortIndex"),
        ],
    )
    conn.executemany(
        "INSERT INTO itemDataValues VALUES (?, ?)",
        [
            (1, "Deep Learning"),
            (2, "2023-05-01"),
            (3, "A study of deep learning"),
            (4, "10.1000/dl"),
            (5, "https://example.com"),
            (6, "Nature"),
            (7, "1-10"),
            (8, "Reinforcement Learning: R&D 100%"),
            (9, "2022-01-01"),
            (10, "File Based Paper"),
            (11, "Ghost Storage Paper"),
            (12, "Absolute Path Paper"),
            (13, "Missing Path Paper"),
            (14, "highlight"),
            (15, "selected text"),
            (16, "my comment"),
            (17, "#ffd400"),
            (18, "3"),
            (19, "00003"),
        ],
    )
    # 条目：1-6 为正式条目；20/21/31-34 附件（type 14）；40 注释（type 15）
    conn.executemany(
        "INSERT INTO items VALUES (?, ?, ?, ?, ?)",
        [
            (1, 1, "ITEM1", "2023-06-01 10:00:00", None),
            (2, 2, "BOOK2", "2023-06-02 10:00:00", None),
            (3, 1, "PAPER3", "2023-06-03 10:00:00", None),
            (4, 1, "PAPER4", "2023-06-04 10:00:00", None),
            (5, 1, "PAPER5", "2023-06-05 10:00:00", None),
            (6, 1, "PAPER6", "2023-06-06 10:00:00", None),
            (20, 14, "ATT20", "2023-06-01 10:00:00", 1),
            (21, 14, "ATT21", "2023-06-02 10:00:00", 2),
            (31, 14, "ATT31", "2023-06-03 10:00:00", 3),
            (32, 14, "ATT32", "2023-06-04 10:00:00", 4),
            (33, 14, "ATT33", "2023-06-05 10:00:00", 5),
            (34, 14, "ATT34", "2023-06-06 10:00:00", 6),
            (40, 15, "ANNO40", "2023-07-01 10:00:00", 20),
        ],
    )
    conn.executemany(
        "INSERT INTO itemData VALUES (?, ?, ?)",
        [
            (1, 1, 1),
            (1, 2, 2),
            (1, 3, 3),
            (1, 4, 4),
            (1, 5, 5),
            (1, 6, 6),
            (1, 7, 7),
            (2, 1, 8),
            (2, 2, 9),
            (3, 1, 10),
            (4, 1, 11),
            (5, 1, 12),
            (6, 1, 13),
            (40, 8, 14),
            (40, 9, 15),
            (40, 10, 16),
            (40, 11, 17),
            (40, 12, 18),
            (40, 13, 19),
        ],
    )
    conn.executemany(
        "INSERT INTO creators VALUES (?, ?, ?)",
        [(1, "Alan", "Turing"), (2, "Geoffrey", "Hinton")],
    )
    conn.execute("INSERT INTO creatorTypes VALUES (1, 'author')")
    conn.executemany(
        "INSERT INTO itemCreators VALUES (?, ?, ?, ?)",
        [(1, 2, 1, 0), (2, 1, 1, 0)],
    )
    conn.executemany(
        "INSERT INTO collections VALUES (?, ?, ?, ?)",
        [(1, "COL1", "Papers", None), (2, "COL2", "SubPapers", 1)],
    )
    conn.executemany("INSERT INTO collectionItems VALUES (?, ?)", [(1, 1), (2, 2)])
    conn.executemany("INSERT INTO tags VALUES (?, ?)", [(1, "ml"), (2, "classic")])
    conn.executemany("INSERT INTO itemTags VALUES (?, ?, ?)", [(1, 1, 0), (2, 2, 0)])
    conn.executemany(
        "INSERT INTO itemAttachments VALUES (?, ?, ?, ?, ?)",
        [
            (20, 1, 0, "application/pdf", "storage:paper.pdf"),
            (21, 2, 3, "text/html", None),
            (31, 3, 0, "application/pdf", "storage:real.pdf"),
            (32, 4, 0, "application/pdf", "storage:ghost.pdf"),
            (33, 5, 0, "application/pdf", str(abs_pdf)),
            (34, 6, 0, "application/pdf", str(storage_dir / "ghost_abs.pdf")),
        ],
    )
    conn.execute("INSERT INTO itemNotes VALUES (50, 1, '<p>note text</p>', 'My Note')")
    # 条目 1 的全文索引：deep learning
    conn.executemany("INSERT INTO fulltextWords VALUES (?, ?)", [(1, "deep"), (2, "learning")])
    conn.executemany("INSERT INTO fulltextItemWords VALUES (?, ?)", [(1, 1), (1, 2)])
    conn.commit()
    conn.close()


@pytest.fixture()
def zotero_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "zotero.sqlite"
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    (storage_dir / "paper.pdf").write_bytes(b"%PDF-1.4 bundled")
    (storage_dir / "real.pdf").write_bytes(b"%PDF-1.4 real")
    abs_pdf = tmp_path / "abs.pdf"
    abs_pdf.write_bytes(b"%PDF-1.4 absolute")
    _build_zotero_db(db_path, storage_dir, abs_pdf)
    return db_path


@pytest.fixture()
def client(zotero_db: Path) -> ZoteroClient:
    return ZoteroClient(db_path=zotero_db)


# ---------------------------------------------------------------------------
# 路径解析
# ---------------------------------------------------------------------------


def test_init_explicit_path(client: ZoteroClient, zotero_db: Path) -> None:
    assert client.db_path == zotero_db


def test_init_nonexistent_raises(tmp_path: Path) -> None:
    with pytest.raises(ZoteroDatabaseNotFoundError):
        ZoteroClient(db_path=tmp_path / "ghost.sqlite")


def test_default_db_paths_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZOTERO_DB_PATH", str(tmp_path / "z.sqlite"))
    assert _default_db_paths() == [tmp_path / "z.sqlite"]


def test_default_db_paths_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZOTERO_DB_PATH", raising=False)
    paths = _default_db_paths()
    assert len(paths) == 3  # Linux / macOS / Windows 三候选
    assert all(p.name == "zotero.sqlite" for p in paths)


# ---------------------------------------------------------------------------
# health_check / get_stats
# ---------------------------------------------------------------------------


def test_health_check_ok(client: ZoteroClient) -> None:
    out = client.health_check()
    assert out["status"] == "ok"
    assert out["item_count"] == 6  # type 14/15 附件与注释不计入
    assert out["db_path"].endswith("zotero.sqlite")


def test_health_check_error_on_garbage_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"this is not a database")
    out = ZoteroClient(db_path=bad).health_check()
    assert out["status"] == "error"
    assert out["error"]


def test_health_check_error_on_empty_schema(tmp_path: Path) -> None:
    empty = tmp_path / "empty.sqlite"
    sqlite3.connect(str(empty)).close()
    out = ZoteroClient(db_path=empty).health_check()
    assert out["status"] == "error"


def test_get_stats(client: ZoteroClient) -> None:
    stats = client.get_stats()
    assert stats == {"items": 6, "collections": 2, "tags": 2, "attachments": 5}


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def test_search_by_title(client: ZoteroClient) -> None:
    results = client.search("Deep")
    assert len(results) == 1
    row = results[0]
    assert row["key"] == "ITEM1"
    assert row["title"] == "Deep Learning"
    assert row["item_type"] == "journalArticle"
    assert row["authors"] == "Hinton Geoffrey"
    assert row["tags"] == ["ml"]
    assert row["date"] == "2023-05-01"


def test_search_by_author(client: ZoteroClient) -> None:
    results = client.search("Turing")
    assert [r["key"] for r in results] == ["BOOK2"]


def test_search_no_match_returns_empty(client: ZoteroClient) -> None:
    assert client.search("quantum_teleportation_xyz") == []


def test_search_order_and_limit(client: ZoteroClient) -> None:
    results = client.search("Paper", limit=2)
    assert [r["key"] for r in results] == ["PAPER6", "PAPER5"]  # dateModified 倒序


def test_search_collection_filter(client: ZoteroClient) -> None:
    assert [r["key"] for r in client.search("Learning", collection_key="COL1")] == ["ITEM1"]
    assert [r["key"] for r in client.search("Learning", collection_key="COL2")] == ["BOOK2"]


def test_search_tag_filter(client: ZoteroClient) -> None:
    assert [r["key"] for r in client.search("Learning", tag="ml")] == ["ITEM1"]
    assert [r["key"] for r in client.search("Learning", tag="classic")] == ["BOOK2"]


def test_search_unknown_collection_raises(client: ZoteroClient) -> None:
    with pytest.raises(ZoteroCollectionNotFoundError):
        client.search("Learning", collection_key="GHOST")


# ---------------------------------------------------------------------------
# get_item
# ---------------------------------------------------------------------------


def test_get_item_full(client: ZoteroClient) -> None:
    item = client.get_item("ITEM1")
    assert item["key"] == "ITEM1"
    assert item["item_type"] == "journalArticle"
    assert item["title"] == "Deep Learning"
    assert item["date"] == "2023-05-01"
    assert item["doi"] == "10.1000/dl"
    assert item["authors"] == [
        {"firstName": "Geoffrey", "lastName": "Hinton", "creatorType": "author"}
    ]
    assert item["tags"] == [{"name": "ml", "type": 0}]
    assert item["collections"] == [{"key": "COL1", "name": "Papers"}]
    assert item["attachments"] == [
        {"itemID": 20, "contentType": "application/pdf", "path": "storage:paper.pdf", "linkMode": 0}
    ]
    assert item["notes"] == [{"title": "My Note", "note": "<p>note text</p>"}]
    assert item["fields"]["publicationTitle"] == "Nature"


def test_get_item_link_mode_3_attachment(client: ZoteroClient) -> None:
    item = client.get_item("BOOK2")
    assert item["attachments"][0]["linkMode"] == 3


def test_get_item_not_found(client: ZoteroClient) -> None:
    with pytest.raises(ZoteroItemNotFoundError):
        client.get_item("NOPE0000")


# ---------------------------------------------------------------------------
# get_annotations
# ---------------------------------------------------------------------------


def test_get_annotations(client: ZoteroClient) -> None:
    annos = client.get_annotations("ITEM1")
    assert len(annos) == 1
    anno = annos[0]
    assert anno["key"] == "ANNO40"
    assert anno["type"] == "highlight"
    assert anno["text"] == "selected text"
    assert anno["comment"] == "my comment"
    assert anno["color"] == "#ffd400"
    assert anno["pageLabel"] == "3"
    assert anno["sortIndex"] == "00003"


def test_get_annotations_no_annotations(client: ZoteroClient) -> None:
    # PAPER3 的 PDF 附件存在但无注释子条目
    assert client.get_annotations("PAPER3") == []


# ---------------------------------------------------------------------------
# list_collections
# ---------------------------------------------------------------------------


def test_list_collections_root(client: ZoteroClient) -> None:
    rows = client.list_collections()
    assert rows == [{"key": "COL1", "name": "Papers", "parentKey": None, "itemCount": 1}]


def test_list_collections_children(client: ZoteroClient) -> None:
    rows = client.list_collections(parent_key="COL1")
    assert rows == [{"key": "COL2", "name": "SubPapers", "parentKey": "COL1", "itemCount": 1}]


def test_list_collections_unknown_raises(client: ZoteroClient) -> None:
    with pytest.raises(ZoteroCollectionNotFoundError):
        client.list_collections(parent_key="GHOST")


# ---------------------------------------------------------------------------
# read_pdf_fulltext
# ---------------------------------------------------------------------------


def test_read_pdf_fulltext_from_index(client: ZoteroClient) -> None:
    out = client.read_pdf_fulltext("ITEM1")
    assert out["source"] == "index"
    assert out["chunk_text"] == "deep learning"
    assert out["total_chars"] == 13
    assert out["has_more"] is False


def test_read_pdf_fulltext_chunking(client: ZoteroClient) -> None:
    out = client.read_pdf_fulltext("ITEM1", chunk_offset=5, max_chars=4)
    assert out["chunk_text"] == "lear"
    assert out["has_more"] is True
    assert out["chunk_offset"] == 5


def test_read_pdf_fulltext_file_storage(client: ZoteroClient) -> None:
    out = client.read_pdf_fulltext("PAPER3")
    assert out["source"] == "file"
    assert Path(out["attachment_path"]).name == "real.pdf"
    assert out["total_chars"] == -1


def test_read_pdf_fulltext_file_absolute(client: ZoteroClient) -> None:
    out = client.read_pdf_fulltext("PAPER5")
    assert out["source"] == "file"
    assert Path(out["attachment_path"]).name == "abs.pdf"


def test_read_pdf_fulltext_unavailable_storage_missing(client: ZoteroClient) -> None:
    out = client.read_pdf_fulltext("PAPER4")
    assert out["source"] == "unavailable"
    assert out["chunk_text"] == ""


def test_read_pdf_fulltext_unavailable_absolute_missing(client: ZoteroClient) -> None:
    out = client.read_pdf_fulltext("PAPER6")
    assert out["source"] == "unavailable"


# ---------------------------------------------------------------------------
# get_bibtex
# ---------------------------------------------------------------------------


def test_get_bibtex_article(client: ZoteroClient) -> None:
    out = client.get_bibtex(["ITEM1"])
    assert "@article{ITEM1," in out
    assert "title = {Deep Learning}," in out
    assert "author = {Hinton, Geoffrey}," in out
    assert "year = {2023}," in out
    assert "journal = {Nature}," in out
    assert "pages = {1-10}," in out
    assert "doi = {10.1000/dl}," in out
    assert "url = {https://example.com}," in out
    assert "abstract = {A study of deep learning}," in out


def test_get_bibtex_escapes_and_book(client: ZoteroClient) -> None:
    out = client.get_bibtex(["BOOK2"])
    assert "@book{BOOK2," in out
    assert r"title = {Reinforcement Learning: R\&D 100\%}," in out
    assert "author = {Turing, Alan}," in out
    assert "year = {2022}," in out


def test_get_bibtex_multiple_entries(client: ZoteroClient) -> None:
    out = client.get_bibtex(["ITEM1", "BOOK2"])
    assert "@article{ITEM1," in out
    assert "@book{BOOK2," in out


def test_get_bibtex_not_found(client: ZoteroClient) -> None:
    with pytest.raises(ZoteroItemNotFoundError):
        client.get_bibtex(["NOPE0000"])


def test_zotero_type_to_bibtex_mapping() -> None:
    to_bibtex = ZoteroClient._zotero_type_to_bibtex
    assert to_bibtex("journalArticle") == "article"
    assert to_bibtex("book") == "book"
    assert to_bibtex("bookSection") == "inbook"
    assert to_bibtex("conferencePaper") == "inproceedings"
    assert to_bibtex("thesis") == "phdthesis"
    assert to_bibtex("report") == "techreport"
    assert to_bibtex("webpage") == "misc"
    assert to_bibtex("manuscript") == "unpublished"
    assert to_bibtex("unknownType") == "misc"


# ---------------------------------------------------------------------------
# 连接异常映射
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", ["database is locked", "unable to open database file"])
def test_connect_locked_raises(
    monkeypatch: pytest.MonkeyPatch, zotero_db: Path, message: str
) -> None:
    def _boom(*args: object, **kwargs: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError(message)

    monkeypatch.setattr(sqlite3, "connect", _boom)
    with pytest.raises(ZoteroDatabaseLockedError):
        ZoteroClient(db_path=zotero_db).get_stats()


def test_connect_other_error_propagates(monkeypatch: pytest.MonkeyPatch, zotero_db: Path) -> None:
    def _boom(*args: object, **kwargs: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(sqlite3, "connect", _boom)
    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        ZoteroClient(db_path=zotero_db).get_stats()
