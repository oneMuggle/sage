"""R78 — Zotero 路由单元测试。

直接调用路由函数。ZoteroClient / settings_repo / 模块级单例 (_client,
_client_db_path) 全 monkeypatch。覆盖：status 可用与不可用（503 信封 /
DB 异常）、search 参数透传与映射、item/annotations 命中与 404、
collections 透传、set_db_path 持久化与单例缓存清空、_get_client 单例
复用与 db_path 变更重建、_get_configured_db_path 的 settings→env 回退、
_item_to_summary/_item_to_detail 映射缺省值。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.api import zotero_routes as zr
from backend.zotero.exceptions import (
    ZoteroDatabaseNotFoundError,
    ZoteroItemNotFoundError,
)

pytestmark = pytest.mark.unit


class _FakeClient:
    def __init__(self, db_path=None):
        self.db_path = db_path
        self.calls = {}
        self.stats = {"items": 3, "collections": 1, "tags": 2, "attachments": 4}

    def get_stats(self):
        return self.stats

    def search(self, **kwargs):
        self.calls["search"] = kwargs
        return [{"key": "K1", "title": "T1"}]

    def get_item(self, key):
        if key == "ghost":
            raise ZoteroItemNotFoundError("item not found: ghost")
        return {"key": key, "title": "Detail"}

    def get_annotations(self, key):
        if key == "ghost":
            raise ZoteroItemNotFoundError("item not found: ghost")
        return [{"key": "an1", "type": "highlight", "text": "t"}]

    def list_collections(self, parent_key=None):
        self.calls["collections"] = parent_key
        return [
            {"key": "C1", "name": "Col", "parent_key": parent_key, "item_count": 2, "version": 5}
        ]


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch):
    monkeypatch.setattr(zr, "_client", None)
    monkeypatch.setattr(zr, "_client_db_path", None)


@pytest.fixture()
def client(monkeypatch):
    fake = _FakeClient(db_path="/z/zotero.sqlite")
    monkeypatch.setattr("backend.zotero.ZoteroClient", lambda db_path=None: fake)
    monkeypatch.setattr(zr, "_get_configured_db_path", lambda: "/z/zotero.sqlite")
    return fake


# ---------------------------------------------------------------------------
# _item_to_summary / _item_to_detail
# ---------------------------------------------------------------------------


def test_item_to_summary_defaults():
    out = zr._item_to_summary({})
    assert out["key"] == ""
    assert out["title"] == ""
    assert out["year"] is None
    assert out["authors"] == []
    assert "attachments" not in out  # summary 不含附件


def test_item_to_detail_defaults():
    out = zr._item_to_detail({"key": "K"})
    assert out["key"] == "K"
    assert out["attachments"] == []
    assert out["doi"] is None
    assert out["url"] is None


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_available(client):
    monkeypatch = client  # noqa: F841 — client fixture 已打桩
    out = zr.get_status()
    assert out["available"] is True
    assert out["error"] is None
    assert out["db_path"].endswith("zotero.sqlite")
    assert out["stats"]["items"] == 3


def test_status_db_not_found_degrades(client, monkeypatch):
    def boom():
        # 构造参数是「搜索过的路径列表」；传字符串会被逐字符 join 成坏消息
        raise ZoteroDatabaseNotFoundError(["/z/zotero.sqlite"])

    monkeypatch.setattr(zr, "_get_client", boom)
    out = zr.get_status()
    assert out["available"] is False
    assert "Zotero database not found" in out["error"]
    assert "/z/zotero.sqlite" in out["error"]
    assert out["stats"] is None


def test_status_503_envelope_degrades(client, monkeypatch):
    def boom():
        raise HTTPException(status_code=503, detail="database is locked")

    monkeypatch.setattr(zr, "_get_client", boom)
    out = zr.get_status()
    assert out["available"] is False
    assert out["error"] == "database is locked"


# ---------------------------------------------------------------------------
# search / item / annotations / collections
# ---------------------------------------------------------------------------


def test_search_items_passes_filters_and_maps(client):
    out = zr.search_items(q="melatonin", collection_key="C1", tag="sleep", limit=7)
    assert client.calls["search"] == {
        "query": "melatonin",
        "collection_key": "C1",
        "tag": "sleep",
        "limit": 7,
    }
    assert out[0]["key"] == "K1"


def test_get_item_hit(client):
    out = zr.get_item("K9")
    assert out["key"] == "K9"
    assert out["title"] == "Detail"


def test_get_item_404(client):
    with pytest.raises(HTTPException) as ei:
        zr.get_item("ghost")
    assert ei.value.status_code == 404
    assert "ghost" in ei.value.detail


def test_annotations_hit_and_404(client):
    out = zr.get_annotations("K1")
    assert out[0]["key"] == "an1"
    with pytest.raises(HTTPException) as ei:
        zr.get_annotations("ghost")
    assert ei.value.status_code == 404


def test_list_collections_passes_parent(client):
    out = zr.list_collections(parent_key="C0")
    assert out[0]["key"] == "C1"
    assert client.calls["collections"] == "C0"


# ---------------------------------------------------------------------------
# set_db_path 持久化与缓存清空
# ---------------------------------------------------------------------------


def test_set_db_path_persists_and_clears_cache(client, monkeypatch):
    saved = {}

    class _Repo:
        def set(self, key, value):
            saved[key] = value

    monkeypatch.setattr("backend.data.settings_repo.SettingsRepository", lambda: _Repo())
    cached = zr._get_client()  # 前置：先让单例进入缓存
    assert cached is client
    out = zr.set_db_path("/new/path.sqlite")
    assert out == {"ok": True, "db_path": "/new/path.sqlite"}
    assert saved == {"zotero_db_path": "/new/path.sqlite"}
    assert zr._client is None  # 缓存被清空，下次请求重建
    assert zr._client_db_path is None


def test_set_db_path_persist_failure_still_ok(client, monkeypatch):
    class _BrokenRepo:
        def set(self, key, value):
            raise RuntimeError("settings locked")

    monkeypatch.setattr("backend.data.settings_repo.SettingsRepository", lambda: _BrokenRepo())
    out = zr.set_db_path("/p.sqlite")
    assert out == {"ok": True, "db_path": "/p.sqlite"}


# ---------------------------------------------------------------------------
# _get_client 单例语义
# ---------------------------------------------------------------------------


def test_get_client_reuses_singleton_for_same_db_path(client):
    first = zr._get_client()
    second = zr._get_client()
    assert first is second


def test_get_client_rebuilds_on_db_path_change(client, monkeypatch):
    first = zr._get_client()
    rebuilt = []
    monkeypatch.setattr(
        "backend.zotero.ZoteroClient",
        lambda db_path=None: rebuilt.append(db_path) or _FakeClient(db_path=db_path),
    )
    second = zr._get_client(db_path_override="/other.sqlite")
    assert second is not first
    # 路由把 override 归一化成 Path 再交给客户端（Windows 下即 WindowsPath）
    assert Path(second.db_path) == Path("/other.sqlite")


def test_get_client_wraps_missing_db_as_503(monkeypatch):
    monkeypatch.setattr(zr, "_client", None)
    monkeypatch.setattr(zr, "_client_db_path", None)
    monkeypatch.setattr(zr, "_get_configured_db_path", lambda: "/missing.sqlite")

    import backend.zotero as zpkg

    class _Raising:
        def __init__(self, db_path=None):
            raise ZoteroDatabaseNotFoundError(["/missing.sqlite"])

    monkeypatch.setattr(zpkg, "ZoteroClient", _Raising)
    with pytest.raises(HTTPException) as ei:
        zr._get_client()
    assert ei.value.status_code == 503
    assert "/missing.sqlite" in ei.value.detail


# ---------------------------------------------------------------------------
# _get_configured_db_path：settings → env 回退
# ---------------------------------------------------------------------------


def test_configured_path_prefers_settings(monkeypatch):
    class _Repo:
        def get(self, key):
            return "/from/settings.sqlite"

    monkeypatch.setattr("backend.data.settings_repo.SettingsRepository", lambda: _Repo())
    monkeypatch.setenv("ZOTERO_DB_PATH", "/from/env.sqlite")
    assert zr._get_configured_db_path() == "/from/settings.sqlite"


def test_configured_path_falls_back_to_env(monkeypatch):
    class _Repo:
        def get(self, key):
            return None

    monkeypatch.setattr("backend.data.settings_repo.SettingsRepository", lambda: _Repo())
    monkeypatch.setenv("ZOTERO_DB_PATH", "/from/env.sqlite")
    assert zr._get_configured_db_path() == "/from/env.sqlite"


def test_configured_path_repo_exception_falls_back_to_env(monkeypatch):
    class _Repo:
        def get(self, key):
            raise RuntimeError("locked")

    monkeypatch.setattr("backend.data.settings_repo.SettingsRepository", lambda: _Repo())
    monkeypatch.setenv("ZOTERO_DB_PATH", "/from/env.sqlite")
    assert zr._get_configured_db_path() == "/from/env.sqlite"
