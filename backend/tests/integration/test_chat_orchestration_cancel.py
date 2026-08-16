"""P2-9/A8 — run 级取消端点全链路：404 / 200 + 落库 + 注册表置位 / 409 终态。"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.data import database as db_mod
from backend.data.orch_run_repo import OrchRun, OrchRunRepository
from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS, ChatDispatcher


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """tmp DB + SAGE_DB_PATH env + 重置全局 _db 单例,挂 main 的 app（含 orch 路由）。"""
    db = tmp_path / "cancel.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()
    from backend.main import app

    return TestClient(app)


def test_cancel_endpoint_lifecycle(client):
    """全链路：404 → 200（落库 cancelled + 注册表置位）→ 409 终态。"""
    repo = OrchRunRepository()

    # 1) run 不存在 → 404
    r = client.post("/api/v1/orch/runs/orch-missing/cancel")
    assert r.status_code == 404

    # 2) running run → 200：DB status 落库 + 注册表 dispatcher 取消事件置位
    repo.upsert(OrchRun(
        run_id="orch-live",
        session_id="s-1",
        status="running",
        created_at=1000,
        plan_json='{"tasks":[]}',
    ))
    dispatcher = ChatDispatcher(
        stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-live"
    )
    _ACTIVE_DISPATCHERS["orch-live"] = dispatcher
    try:
        r = client.post("/api/v1/orch/runs/orch-live/cancel")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {"ok": True, "run_id": "orch-live", "status": "cancelled"}
        # 注册表命中 → 同步置位（running 子任务不硬杀，只停新任务）
        assert dispatcher._cancelled.is_set()
        # repo.update_status 落库断言
        updated = repo.get("orch-live")
        assert updated is not None
        assert updated.status == "cancelled"
    finally:
        _ACTIVE_DISPATCHERS.pop("orch-live", None)

    # 3) 终态再次 cancel → 409
    r = client.post("/api/v1/orch/runs/orch-live/cancel")
    assert r.status_code == 409
    assert "terminal state" in r.json()["detail"]
