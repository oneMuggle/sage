"""r95 — Zotero MCP server 单测（9 工具分发 + JSON 信封 + 错误兜底）。

fake client 注入模块单例 ``_client``，不经真实 SQLite。``call_tool``/
``list_tools`` 在 MCP 可用与不可用两种安装形态下都是可直接调用的异步函数
（SDK 装饰器注册并原样返回函数；无 MCP 时为恒等装饰器）。
"""

from __future__ import annotations

import json

import pytest

from backend.mcp.servers.zotero import server as zotero_server
from backend.zotero import service as zotero_service

pytestmark = pytest.mark.unit


class _FakeClient:
    """ZoteroClient 替身：记录调用参数，返回固定数据。"""

    def __init__(self, calls: dict, health_status: str = "ok"):
        self.calls = calls
        self.health_status = health_status

    def health_check(self):
        return {"status": self.health_status, "db_path": "/fake/zotero.sqlite"}

    def get_stats(self):
        return {"items": 10, "collections": 2, "tags": 5, "attachments": 3}

    def search(self, query, collection_key=None, tag=None, limit=20):
        self.calls["search"] = {
            "query": query, "collection_key": collection_key, "tag": tag, "limit": limit,
        }
        return [{"key": "ITEM1", "title": "A Paper"}]

    def get_item(self, item_key):
        self.calls.setdefault("get_item_calls", []).append(item_key)
        return {
            "key": item_key,
            "title": "A Paper",
            "doi": "10.1/xx",
            "authors": [],
            "tags": [],
            "date": "2024",
            "item_type": "journalArticle",
        }

    def get_annotations(self, item_key):
        self.calls["get_annotations"] = item_key
        return [{"key": "AN1", "type": "highlight", "text": "txt"}]

    def list_collections(self, parent_key=None):
        self.calls["list_collections"] = parent_key
        return [{"key": "CK1", "name": "Root", "parentKey": None}]

    def get_bibtex(self, item_keys):
        self.calls["get_bibtex"] = list(item_keys)
        return "@article{a,\n  title = {A Paper},\n}\n"

    def read_pdf_fulltext(self, item_key, chunk_offset=0, chunk_size=10000, max_chars=50000):
        self.calls["read_pdf"] = {
            "item_key": item_key,
            "chunk_offset": chunk_offset,
            "chunk_size": chunk_size,
            "max_chars": max_chars,
        }
        return {"item_key": item_key, "text": "chunk-body", "has_more": False}

    def get_related_items(self, item_key):
        self.calls["related"] = item_key
        return [
            {
                "key": "REL1",
                "title": "Related Paper",
                "item_type": "journalArticle",
                "date": "2023",
                "authors": [],
                "tags": [],
            }
        ]


@pytest.fixture()
def calls():
    return {}


@pytest.fixture()
def fake_client(calls, monkeypatch):
    fake = _FakeClient(calls)
    monkeypatch.setattr(zotero_server, "_client", fake)
    return fake


def _text(result) -> str:
    assert len(result) == 1
    return result[0].text


@pytest.mark.asyncio()
async def test_list_tools_exposes_nine(fake_client):
    tools = await zotero_server.list_tools()
    names = [t.name for t in tools]
    assert names == [
        "zotero_status",
        "zotero_search",
        "zotero_get_item",
        "zotero_get_annotations",
        "zotero_list_collections",
        "zotero_get_bibtex",
        "zotero_read_pdf",
        "zotero_related",
        "zotero_sync",
    ]
    # 每个工具都带 JSON Schema
    assert all(isinstance(t.inputSchema, dict) and t.inputSchema.get("type") == "object" for t in tools)


@pytest.mark.asyncio()
async def test_status_ok_returns_health_and_stats(fake_client):
    out = await zotero_server.call_tool("zotero_status", {})
    body = json.loads(_text(out))
    assert body["health"]["status"] == "ok"
    assert body["stats"]["items"] == 10


@pytest.mark.asyncio()
async def test_status_unhealthy_returns_health_only(calls, monkeypatch):
    monkeypatch.setattr(zotero_server, "_client", _FakeClient(calls, health_status="not_found"))
    out = await zotero_server.call_tool("zotero_status", {})
    body = json.loads(_text(out))
    assert body == {"status": "not_found", "db_path": "/fake/zotero.sqlite"}


@pytest.mark.asyncio()
async def test_search_passes_args_and_wraps_envelope(fake_client, calls):
    out = await zotero_server.call_tool(
        "zotero_search",
        {"query": "paper", "collection_key": "CK1", "tag": "ml", "limit": 5},
    )
    body = json.loads(_text(out))
    assert calls["search"] == {"query": "paper", "collection_key": "CK1", "tag": "ml", "limit": 5}
    assert body == {
        "query": "paper",
        "mode": "sql",
        "total": 1,
        "results": [{"key": "ITEM1", "title": "A Paper"}],
    }


@pytest.mark.asyncio()
async def test_search_missing_required_arg_falls_into_error_text(fake_client):
    out = await zotero_server.call_tool("zotero_search", {})
    text = _text(out)
    assert text.startswith("Error: Zotero tool 'zotero_search' failed:")
    # KeyError 的字符串化是缺失键本身（'query'），不含异常类名
    assert "'query'" in text


@pytest.mark.asyncio()
async def test_search_falls_back_to_sql_when_semantic_return_zero_hits(
    fake_client, calls, monkeypatch
):
    """H4 — 向量库可用但 0 命中时必须退回 SQL LIKE，不能返回空结果。"""
    async def _empty_semantic(query, limit=20, client=None):
        return []  # RAG 可用但无命中

    monkeypatch.setattr(zotero_service, "semantic_search", _empty_semantic)

    out = await zotero_server.call_tool("zotero_search", {"query": "obscure term"})
    body = json.loads(_text(out))

    # 落到 SQL 模式并返回 fake client 的固定命中
    assert body["mode"] == "sql"
    assert body["total"] == 1
    assert body["results"] == [{"key": "ITEM1", "title": "A Paper"}]
    assert calls["search"]["query"] == "obscure term"


@pytest.mark.asyncio()
async def test_search_falls_back_to_sql_when_semantic_unavailable(
    fake_client, calls, monkeypatch
):
    """向量库不可用（None）走 SQL LIKE —— 既有路径不被 H4 改动破坏。"""
    async def _unavailable(query, limit=20, client=None):
        return None

    monkeypatch.setattr(zotero_service, "semantic_search", _unavailable)

    out = await zotero_server.call_tool("zotero_search", {"query": "anything"})
    body = json.loads(_text(out))
    assert body["mode"] == "sql"


@pytest.mark.asyncio()
async def test_get_item_returns_raw_item_json(fake_client, calls):
    out = await zotero_server.call_tool("zotero_get_item", {"item_key": "ITEM9"})
    body = json.loads(_text(out))
    assert calls["get_item_calls"] == ["ITEM9"]
    assert body == {
        "key": "ITEM9",
        "title": "A Paper",
        "doi": "10.1/xx",
        "authors": [],
        "tags": [],
        "date": "2024",
        "item_type": "journalArticle",
    }


@pytest.mark.asyncio()
async def test_annotations_envelope(fake_client, calls):
    out = await zotero_server.call_tool("zotero_get_annotations", {"item_key": "ITEM1"})
    body = json.loads(_text(out))
    assert calls["get_annotations"] == "ITEM1"
    assert body["total"] == 1
    assert body["annotations"][0]["key"] == "AN1"
    assert body["item_key"] == "ITEM1"


@pytest.mark.asyncio()
async def test_collections_parent_key_passthrough(fake_client, calls):
    out = await zotero_server.call_tool("zotero_list_collections", {"parent_key": "P1"})
    body = json.loads(_text(out))
    assert calls["list_collections"] == "P1"
    assert body["total"] == 1
    # 缺省 → None（顶层）
    await zotero_server.call_tool("zotero_list_collections", {})
    assert calls["list_collections"] is None


@pytest.mark.asyncio()
async def test_bibtex_returns_raw_text(fake_client, calls):
    out = await zotero_server.call_tool("zotero_get_bibtex", {"item_keys": ["A", "B"]})
    text = _text(out)
    assert calls["get_bibtex"] == ["A", "B"]
    assert text.startswith("@article{a,")
    assert "json" not in text[:1]  # 非 JSON 信封


@pytest.mark.asyncio()
async def test_read_pdf_defaults_and_overrides(fake_client, calls):
    out = await zotero_server.call_tool("zotero_read_pdf", {"item_key": "ITEM1"})
    body = json.loads(_text(out))
    assert calls["read_pdf"] == {"item_key": "ITEM1", "chunk_offset": 0, "chunk_size": 10000, "max_chars": 50000}
    assert body["text"] == "chunk-body"
    await zotero_server.call_tool(
        "zotero_read_pdf", {"item_key": "ITEM1", "chunk_offset": 2, "chunk_size": 500, "max_chars": 900},
    )
    assert calls["read_pdf"]["chunk_offset"] == 2
    assert calls["read_pdf"]["chunk_size"] == 500
    assert calls["read_pdf"]["max_chars"] == 900


@pytest.mark.asyncio()
async def test_unknown_tool_returns_message(fake_client):
    out = await zotero_server.call_tool("zotero_nonexistent", {})
    assert _text(out) == "Unknown Zotero tool: zotero_nonexistent"


@pytest.mark.asyncio()
async def test_related_merges_zotero_and_wiki_keys(fake_client, calls, monkeypatch):
    monkeypatch.setattr(
        zotero_service, "wiki_related_keys",
        lambda project_path, item_key: ["WIKI1", "REL1"],
    )
    out = await zotero_server.call_tool(
        "zotero_related", {"item_key": "ITEM1", "project_path": "/proj"},
    )
    body = json.loads(_text(out))
    assert calls["related"] == "ITEM1"
    assert body["item_key"] == "ITEM1"
    # REL1 来自 Zotero（get_related_items），WIKI1 来自 wiki；REL1 去重（不重复出现）
    keys = [r["key"] for r in body["related"]]
    assert "REL1" in keys
    assert "WIKI1" in keys
    assert keys.count("REL1") == 1
    # ITEM1 自身不出现在 related 中
    assert "ITEM1" not in keys


@pytest.mark.asyncio()
async def test_sync_dispatches_incremental_vs_full(fake_client, monkeypatch):
    """zotero_sync 工具：force 默认走增量，force=true 走全量。"""

    class _FakeResult:
        def __init__(self, mode):
            self.mode = mode

        def to_dict(self):
            return {"mode": self.mode, "items": 3, "errors": []}

    class _FakeIngestor:
        def __init__(self):
            self.calls = []

        async def sync_incremental(self):
            self.calls.append("incremental")
            return _FakeResult("incremental")

        async def sync_full(self):
            self.calls.append("full")
            return _FakeResult("full")

    ingestor = _FakeIngestor()
    monkeypatch.setattr(zotero_service, "build_client", lambda: fake_client)
    monkeypatch.setattr(zotero_service, "build_ingestor", lambda client: ingestor)

    out_default = await zotero_server.call_tool("zotero_sync", {})
    body_default = json.loads(_text(out_default))
    assert body_default["mode"] == "incremental"

    out_force = await zotero_server.call_tool("zotero_sync", {"force": True})
    body_force = json.loads(_text(out_force))
    assert body_force["mode"] == "full"
    assert ingestor.calls == ["incremental", "full"]
