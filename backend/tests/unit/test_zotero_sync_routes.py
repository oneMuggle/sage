"""M3 — Zotero 同步 REST 端点单测（POST /sync, GET /sync-status）。

覆盖：
- 并发保护（409 Conflict）
- DB 未配置（503）
- force 全量 vs 增量分发
- sync-status 字段（vector_dim, embedding_configured, sync_in_progress）
- 启动期后台同步的首次跳过 / 锁占用跳过
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import zotero_sync_routes
from backend.zotero import service as zotero_service

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeSyncResult:
    def __init__(self, mode: str, items: int = 3, errors: list | None = None):
        self.mode = mode
        self.items = items
        self.errors = errors or []

    def to_dict(self) -> Dict[str, Any]:
        return {"mode": self.mode, "items": self.items, "errors": self.errors}


class _FakeIngestor:
    """记录调用模式（incremental / full），返回固定结果。"""

    def __init__(self):
        self.calls: list = []

    async def sync_incremental(self):
        self.calls.append("incremental")
        return _FakeSyncResult("incremental")

    async def sync_full(self):
        self.calls.append("full")
        return _FakeSyncResult("full")


class _FakeClient:
    pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    fastapi = FastAPI()
    fastapi.include_router(zotero_sync_routes.router)
    return fastapi


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_sync_state(monkeypatch):
    """每个测试都重置锁与进度标志，避免跨测试泄漏。"""
    monkeypatch.setattr(zotero_sync_routes, "_sync_lock", asyncio.Lock())
    monkeypatch.setattr(zotero_sync_routes, "_sync_in_progress", False)


# ---------------------------------------------------------------------------
# POST /sync
# ---------------------------------------------------------------------------


def test_sync_incremental_by_default(client, monkeypatch):
    ingestor = _FakeIngestor()
    monkeypatch.setattr(zotero_service, "build_client", lambda: _FakeClient())
    monkeypatch.setattr(zotero_service, "build_ingestor", lambda c: ingestor)

    resp = client.post("/sync", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "incremental"
    assert ingestor.calls == ["incremental"]


def test_sync_force_dispatches_full(client, monkeypatch):
    ingestor = _FakeIngestor()
    monkeypatch.setattr(zotero_service, "build_client", lambda: _FakeClient())
    monkeypatch.setattr(zotero_service, "build_ingestor", lambda c: ingestor)

    resp = client.post("/sync", json={"force": True})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "full"
    assert ingestor.calls == ["full"]


def test_sync_returns_503_when_no_database(client, monkeypatch):
    monkeypatch.setattr(zotero_service, "build_client", lambda: None)

    resp = client.post("/sync", json={})
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


def test_sync_returns_409_when_already_running(client, monkeypatch):
    """并发保护：锁被占用时立即 409，不排队。"""
    # ``_sync_lock`` 现在是 ``LazyLock``；用一个满足 ``.locked()`` 接口的桩对象
    # 避免依赖事件循环（py3.12+ 已弃用 ``get_event_loop()`` 同步构造）
    class _HeldLock:
        def locked(self) -> bool:
            return True

        async def __aenter__(self) -> _HeldLock:  # pragma: no cover - 409 早退
            raise AssertionError("lock should short-circuit via .locked()")

        async def __aexit__(self, *args: Any) -> None:  # pragma: no cover
            pass

    monkeypatch.setattr(zotero_sync_routes, "_sync_lock", _HeldLock())
    monkeypatch.setattr(zotero_service, "build_client", lambda: _FakeClient())

    resp = client.post("/sync", json={})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /sync-status
# ---------------------------------------------------------------------------


def test_sync_status_shape(client, monkeypatch, tmp_path):
    """sync-status 返回完整字段，vector_dim/embedding_configured 来自 service 层。"""
    monkeypatch.setattr(zotero_service, "stored_summary", lambda: (384, 12))
    monkeypatch.setattr(zotero_service, "embed_config", lambda: object())
    # settings repo 返回空状态 → last_sync_ts 为 None
    monkeypatch.setattr(zotero_sync_routes, "_load_sync_state", lambda: {})

    resp = client.get("/sync-status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["vector_dim"] == 384
    assert body["item_count"] == 12  # max(0, record_count=12)
    assert body["embedding_configured"] is True
    assert body["sync_in_progress"] is False
    assert body["last_sync_ts"] is None
    assert body["errors"] == []


def test_sync_status_item_count_uses_max(client, monkeypatch):
    """item_count 取 state.items 与 record_count 较大值，避免漂移。"""
    monkeypatch.setattr(zotero_service, "stored_summary", lambda: (384, 5))
    monkeypatch.setattr(zotero_service, "embed_config", lambda: None)
    monkeypatch.setattr(
        zotero_sync_routes, "_load_sync_state",
        lambda: {"items": 20, "wiki_pages": 3},
    )

    body = client.get("/sync-status").json()
    assert body["item_count"] == 20  # max(20, 5)
    assert body["wiki_page_count"] == 3
    assert body["embedding_configured"] is False


# ---------------------------------------------------------------------------
# run_background_sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_background_sync_skips_when_no_watermark(monkeypatch):
    """首次启动：没有 last_sync_ts → 直接跳过（不自动全量索引）。"""
    monkeypatch.setattr(zotero_sync_routes, "_load_sync_state", lambda: {})
    build_calls = []
    monkeypatch.setattr(
        zotero_service, "build_client",
        lambda: build_calls.append(1) or _FakeClient(),
    )

    await zotero_sync_routes.run_background_sync()
    assert build_calls == []  # 根本没尝试构造客户端


@pytest.mark.asyncio()
async def test_background_sync_skips_when_no_database(monkeypatch):
    monkeypatch.setattr(
        zotero_sync_routes, "_load_sync_state",
        lambda: {"last_sync_ts": 1700000000},
    )
    monkeypatch.setattr(zotero_service, "build_client", lambda: None)
    ingestor_calls = []
    monkeypatch.setattr(
        zotero_service, "build_ingestor",
        lambda c: ingestor_calls.append(1) or _FakeIngestor(),
    )

    await zotero_sync_routes.run_background_sync()
    assert ingestor_calls == []  # 没有客户端 → 不构造 ingestor


@pytest.mark.asyncio()
async def test_background_sync_runs_incremental_when_watermark_present(monkeypatch):
    """有水位 + 有 DB → 跑一次增量。"""
    monkeypatch.setattr(
        zotero_sync_routes, "_load_sync_state",
        lambda: {"last_sync_ts": 1700000000},
    )
    monkeypatch.setattr(zotero_service, "build_client", lambda: _FakeClient())
    ingestor = _FakeIngestor()
    monkeypatch.setattr(zotero_service, "build_ingestor", lambda c: ingestor)

    await zotero_sync_routes.run_background_sync()
    assert ingestor.calls == ["incremental"]


@pytest.mark.asyncio()
async def test_background_sync_skips_when_lock_held(monkeypatch):
    """手动同步正在进行时，后台同步直接跳过（不排队）。"""
    held_lock = asyncio.Lock()
    await held_lock.acquire()
    monkeypatch.setattr(zotero_sync_routes, "_sync_lock", held_lock)
    monkeypatch.setattr(
        zotero_sync_routes, "_load_sync_state",
        lambda: {"last_sync_ts": 1700000000},
    )
    ingestor_calls = []
    monkeypatch.setattr(
        zotero_service, "build_ingestor",
        lambda c: ingestor_calls.append(1) or _FakeIngestor(),
    )

    await zotero_sync_routes.run_background_sync()
    assert ingestor_calls == []


# ---------------------------------------------------------------------------
# Persisted wiki project binding
# ---------------------------------------------------------------------------


def test_sync_uses_persisted_wiki_project(client, monkeypatch):
    """POST /sync without project_path falls back to the saved binding."""
    ingestor = _FakeIngestor()
    monkeypatch.setattr(zotero_service, "build_client", lambda: _FakeClient())
    monkeypatch.setattr(zotero_service, "build_ingestor", lambda c: ingestor)
    monkeypatch.setattr(
        zotero_sync_routes, "_configured_wiki_project", lambda: "/bound/project"
    )
    seen = {}

    def fake_export(client_obj, project_path):
        seen["path"] = project_path
        return {"items_exported": 1, "authors_exported": 0, "errors": []}

    monkeypatch.setattr(zotero_sync_routes, "_run_wiki_export", fake_export)
    monkeypatch.setattr(zotero_sync_routes, "_record_wiki_pages", lambda count: None)

    resp = client.post("/sync", json={})
    assert resp.status_code == 200
    assert seen["path"] == "/bound/project"
    assert resp.json()["wiki"]["items_exported"] == 1


def test_sync_status_exposes_wiki_project(client, monkeypatch):
    monkeypatch.setattr(zotero_service, "stored_summary", lambda: (None, 0))
    monkeypatch.setattr(zotero_service, "embed_config", lambda: None)
    monkeypatch.setattr(zotero_sync_routes, "_load_sync_state", lambda: {})
    monkeypatch.setattr(
        zotero_sync_routes, "_configured_wiki_project", lambda: "/bound/project"
    )

    body = client.get("/sync-status").json()
    assert body["wiki_project_path"] == "/bound/project"


@pytest.mark.asyncio()
async def test_background_sync_exports_wiki_when_bound(monkeypatch):
    monkeypatch.setattr(
        zotero_sync_routes, "_load_sync_state",
        lambda: {"last_sync_ts": 1700000000},
    )
    monkeypatch.setattr(zotero_service, "build_client", lambda: _FakeClient())
    monkeypatch.setattr(zotero_service, "build_ingestor", lambda c: _FakeIngestor())
    monkeypatch.setattr(
        zotero_sync_routes, "_configured_wiki_project", lambda: "/bound/project"
    )
    seen = {}

    def fake_export(client_obj, project_path):
        seen["path"] = project_path
        return {"items_exported": 2, "authors_exported": 1, "errors": []}

    monkeypatch.setattr(zotero_sync_routes, "_run_wiki_export", fake_export)
    monkeypatch.setattr(zotero_sync_routes, "_record_wiki_pages", lambda count: None)

    await zotero_sync_routes.run_background_sync()
    assert seen["path"] == "/bound/project"
