"""r95 — Zotero MCP server 单测（7 工具分发 + JSON 信封 + 错误兜底）。

fake client 注入模块单例 ``_client``，不经真实 SQLite。``call_tool``/
``list_tools`` 在 MCP 可用与不可用两种安装形态下都是可直接调用的异步函数
（SDK 装饰器注册并原样返回函数；无 MCP 时为恒等装饰器）。
"""

from __future__ import annotations

import json

import pytest

from backend.mcp.servers.zotero import server as zotero_server

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
        self.calls["get_item"] = item_key
        return {"key": item_key, "title": "A Paper", "doi": "10.1/xx"}

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
async def test_list_tools_exposes_seven(fake_client):
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
    assert body == {"query": "paper", "total": 1, "results": [{"key": "ITEM1", "title": "A Paper"}]}


@pytest.mark.asyncio()
async def test_search_missing_required_arg_falls_into_error_text(fake_client):
    out = await zotero_server.call_tool("zotero_search", {})
    text = _text(out)
    assert text.startswith("Error: Zotero tool 'zotero_search' failed:")
    # KeyError 的字符串化是缺失键本身（'query'），不含异常类名
    assert "'query'" in text


@pytest.mark.asyncio()
async def test_get_item_returns_raw_item_json(fake_client, calls):
    out = await zotero_server.call_tool("zotero_get_item", {"item_key": "ITEM9"})
    body = json.loads(_text(out))
    assert calls["get_item"] == "ITEM9"
    assert body == {"key": "ITEM9", "title": "A Paper", "doi": "10.1/xx"}


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
