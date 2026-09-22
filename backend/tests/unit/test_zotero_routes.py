"""r94 — Zotero REST 路由单测（status / search / items / annotations / collections / path）。

ZoteroClient 以模块级单例注入：测试用 fake client 替换 ``zotero_routes._client``，
不走真实 SQLite。503 路径通过让构造函数抛 ZoteroDatabaseNotFoundError 触发。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import zotero_routes
from backend.zotero.exceptions import ZoteroDatabaseNotFoundError, ZoteroItemNotFoundError

pytestmark = pytest.mark.unit


class _FakeClient:
    """返回固定数据的 ZoteroClient 替身，记录调用参数。"""

    db_path = "/fake/zotero.sqlite"

    def __init__(self, calls: dict | None = None):
        self.calls = calls if calls is not None else {}

    def get_stats(self):
        self.calls["get_stats"] = True
        return {"items": 10, "collections": 2, "tags": 5, "attachments": 3}

    def search(self, query="", collection_key=None, tag=None, limit=20):
        self.calls["search"] = {
            "query": query, "collection_key": collection_key, "tag": tag, "limit": limit,
        }
        return [{
            "key": "ITEM1", "title": "A Paper", "item_type": "journalArticle",
            "year": 2024, "authors": ["Author A"], "abstract": "abs",
            "collections": ["CK1"], "tags": ["ml"], "date_added": "2024-01-01T00:00:00Z",
        }]

    def get_item(self, item_key: str):
        self.calls["get_item"] = item_key
        if item_key == "MISSING":
            raise ZoteroItemNotFoundError(item_key)
        return {
            "key": item_key, "title": "A Paper", "item_type": "journalArticle",
            "year": 2024, "authors": ["Author A"], "abstract": "abs",
            "collections": [], "tags": [], "date_added": "2024-01-01T00:00:00Z",
            "date_modified": "2024-02-01T00:00:00Z", "extra": "extra-x",
            "doi": "10.1/xx", "url": "https://example.org/a",
            "attachments": [{"key": "AT1", "filename": "a.pdf", "path": "/p/a.pdf"}],
        }

    def get_annotations(self, item_key: str):
        self.calls["get_annotations"] = item_key
        if item_key == "MISSING":
            raise ZoteroItemNotFoundError(item_key)
        return [{
            "key": "AN1", "type": "highlight", "text": "txt", "comment": None,
            "color": "#ffd400", "page_label": "3", "date_added": "2024-01-02T00:00:00Z",
        }]

    def list_collections(self, parent_key=None):
        self.calls["list_collections"] = parent_key
        return [{"key": "CK1", "name": "Root", "parent_key": None,
                 "item_count": 4, "version": 7}]


@pytest.fixture()
def calls():
    return {}


@pytest.fixture()
def client(calls, monkeypatch):
    fake = _FakeClient(calls)
    # 单例注入：_get_client 直接命中缓存分支，不构造真实 client。
    # 配置读取一并钉死为 None，避免 CI 环境变量 ZOTERO_DB_PATH 干扰缓存匹配。
    monkeypatch.setattr(zotero_routes, "_client", fake)
    monkeypatch.setattr(zotero_routes, "_client_db_path", None)
    monkeypatch.setattr(zotero_routes, "_get_configured_db_path", lambda: None)
    app = FastAPI()
    app.include_router(zotero_routes.router)
    return TestClient(app)


def test_zotero_db_path_in_settings_whitelist():
    """r94 回归: 白名单缺 key 时 set() 抛 ValueError, /path 静默丢失配置。"""
    from backend.data.settings_repo import SettingsRepository

    assert "zotero_db_path" in SettingsRepository.KEYS


def test_status_available(client, calls):
    res = client.get("/zotero/status")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["available"] is True
    assert body["db_path"] == "/fake/zotero.sqlite"
    assert body["error"] is None
    assert body["stats"] == {"items": 10, "collections": 2, "tags": 5, "attachments": 3}
    assert calls.get("get_stats") is True


def test_status_unavailable_returns_200_with_error(monkeypatch):
    def _boom():
        raise ZoteroDatabaseNotFoundError(["C:/a", "C:/b"])

    monkeypatch.setattr(zotero_routes, "_client", None)
    monkeypatch.setattr(zotero_routes, "_client_db_path", None)
    monkeypatch.setattr(zotero_routes, "_get_client", _boom)
    app = FastAPI()
    app.include_router(zotero_routes.router)
    res = TestClient(app).get("/zotero/status")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["available"] is False
    assert "not found" in body["error"]
    assert body["stats"] is None


def test_search_passes_params_and_maps_summary(client, calls):
    res = client.get("/zotero/search", params={"q": "paper", "collection_key": "CK1", "tag": "ml", "limit": 5})
    assert res.status_code == 200, res.text
    assert calls["search"] == {"query": "paper", "collection_key": "CK1", "tag": "ml", "limit": 5}
    item = res.json()[0]
    assert item["key"] == "ITEM1"
    assert item["year"] == 2024
    assert item["authors"] == ["Author A"]
    assert "date_modified" not in item  # summary 不带 detail 字段


def test_search_limit_out_of_range_rejected(client):
    assert client.get("/zotero/search", params={"limit": 0}).status_code == 422
    assert client.get("/zotero/search", params={"limit": 101}).status_code == 422


def test_get_item_detail_mapping(client, calls):
    res = client.get("/zotero/items/ITEM9")
    assert res.status_code == 200, res.text
    assert calls["get_item"] == "ITEM9"
    body = res.json()
    assert body["doi"] == "10.1/xx"
    assert body["extra"] == "extra-x"
    assert body["attachments"][0]["filename"] == "a.pdf"


def test_get_item_missing_returns_404(client):
    res = client.get("/zotero/items/MISSING")
    assert res.status_code == 404, res.text
    assert "MISSING" in res.json()["detail"]


def test_annotations_roundtrip_and_404(client, calls):
    ok = client.get("/zotero/items/ITEM1/annotations")
    assert ok.status_code == 200, ok.text
    ann = ok.json()[0]
    assert ann["type"] == "highlight"
    assert ann["page_label"] == "3"
    missing = client.get("/zotero/items/MISSING/annotations")
    assert missing.status_code == 404


def test_collections_parent_key_passthrough(client, calls):
    assert client.get("/zotero/collections").status_code == 200
    assert calls["list_collections"] is None
    client.get("/zotero/collections", params={"parent_key": "P1"})
    assert calls["list_collections"] == "P1"


def test_set_db_path_responds_ok_and_clears_singleton(client, monkeypatch):
    # 拦截 SettingsRepository.set，避免写真实用户配置
    saved = {}

    class _FakeRepo:
        def get(self, key):
            return saved.get(key)

        def set(self, key, value):
            saved[key] = value

    import backend.data.settings_repo as settings_repo_mod
    monkeypatch.setattr(settings_repo_mod, "SettingsRepository", _FakeRepo)

    # 先让单例非空，验证 /path 清缓存语义
    monkeypatch.setattr(zotero_routes, "_client", object())
    monkeypatch.setattr(zotero_routes, "_client_db_path", "/old")

    res = client.post("/zotero/path", params={"path": "C:/zotero.sqlite"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body == {"ok": True, "db_path": "C:/zotero.sqlite"}
    assert saved.get("zotero_db_path") == "C:/zotero.sqlite"
    assert zotero_routes._client is None
    assert zotero_routes._client_db_path is None


def test_client_constructor_failure_raises_503(monkeypatch):
    """DB 找不到时，search 等端点应 503（前端展示"配置路径"提示）。"""
    def _raising_client(*args, **kwargs):
        raise ZoteroDatabaseNotFoundError(["C:/none"])

    import backend.zotero as zotero_pkg
    monkeypatch.setattr(zotero_routes, "_client", None)
    monkeypatch.setattr(zotero_routes, "_client_db_path", None)
    monkeypatch.setattr(zotero_pkg, "ZoteroClient", _raising_client)
    app = FastAPI()
    app.include_router(zotero_routes.router)
    res = TestClient(app).get("/zotero/search")
    assert res.status_code == 503, res.text
    assert "not found" in res.json()["detail"]
