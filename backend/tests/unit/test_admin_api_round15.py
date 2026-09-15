"""管理面收口测试（Round 15: 建议采纳 + 网关绑定管理）"""

from __future__ import annotations

import tempfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.gateway_routes import router as gateway_router
from backend.api.legacy_routes import router as legacy_router
from backend.data.database import Database
from backend.skills.audit import SkillAuditLog
from backend.skills.lifecycle import SkillLifecycleStore

pytestmark = pytest.mark.unit


@pytest.fixture()
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
        yield db
        db.close()


class TestConsolidationAccept:
    @pytest.fixture()
    def client(self):
        app = FastAPI()
        app.include_router(legacy_router)
        return TestClient(app, headers={"Authorization": "Bearer test-local-auth-token"})

    def test_accept_archives_skills(self, tmp_db, client, monkeypatch):
        from backend.skills.audit import SkillAuditLog as _Log

        # 审计单例与 lifecycle 都绑定 tmp_db（route 内部走 get_database 全局）
        monkeypatch.setattr(
            "backend.skills.audit._skill_audit_log", _Log(db=tmp_db)
        )
        store = SkillLifecycleStore(db=tmp_db)
        import backend.skills.lifecycle as lifecycle_mod

        monkeypatch.setattr(lifecycle_mod, "get_lifecycle_store", lambda: store)
        known = [{"name": "old-a"}, {"name": "old-b"}]
        adapter = SimpleNamespace(list_skills_extended=lambda: known)
        monkeypatch.setattr(
            "backend.api.legacy_routes._get_skill_adapter", lambda: adapter
        )

        resp = client.post(
            "/skills/consolidation/accept", json={"skill_names": ["old-a", "old-b"]}
        )
        assert resp.status_code == 200
        assert resp.json()["archived"] == ["old-a", "old-b"]
        # 走 lifecycle → 审计台账（Round 3 挂钩）
        audit = SkillAuditLog(db=tmp_db)
        actions = [e["action"] for e in audit.list_entries()]
        assert actions == ["archive", "archive"]

    def test_accept_pinned_skipped(self, tmp_db, client, monkeypatch):
        store = SkillLifecycleStore(db=tmp_db)
        store.set_pinned("pinned-a", True)
        import backend.skills.lifecycle as lifecycle_mod

        monkeypatch.setattr(lifecycle_mod, "get_lifecycle_store", lambda: store)
        adapter = SimpleNamespace(list_skills_extended=lambda: [{"name": "pinned-a"}])
        monkeypatch.setattr(
            "backend.api.legacy_routes._get_skill_adapter", lambda: adapter
        )

        resp = client.post(
            "/skills/consolidation/accept", json={"skill_names": ["pinned-a"]}
        )
        assert resp.status_code == 200
        assert resp.json()["skipped_pinned"] == ["pinned-a"]
        assert store.is_pinned("pinned-a")

    def test_accept_empty_names_400(self, client):
        resp = client.post("/skills/consolidation/accept", json={"skill_names": []})
        assert resp.status_code == 400


class TestGatewayBinds:
    @pytest.fixture()
    def client(self):
        app = FastAPI()
        app.include_router(gateway_router)
        return TestClient(app, headers={"Authorization": "Bearer test-local-auth-token"})

    def _gateway(self, tmp_db):
        from backend.gateway.telegram import TelegramConfig, TelegramGateway

        config = TelegramConfig(bot_token="tok", allowed_chat_ids=["111"])
        return TelegramGateway(config=config, transport=SimpleNamespace(), db=tmp_db)

    def test_bind_unbind_roundtrip(self, tmp_db, client, monkeypatch):
        import backend.gateway.telegram as tg_mod

        gateway = self._gateway(tmp_db)
        monkeypatch.setattr(tg_mod, "_gateway", gateway)
        gateway._conn().execute(
            "INSERT INTO telegram_chats (chat_id, session_id, created_at) "
            "VALUES ('c1', 's1', 1)"
        )
        gateway._conn().commit()

        resp = client.get("/gateway/telegram/binds")
        assert resp.status_code == 200
        assert len(resp.json()["binds"]) == 1

        resp = client.delete("/gateway/telegram/binds/c1")
        assert resp.status_code == 200
        resp = client.delete("/gateway/telegram/binds/c1")
        assert resp.status_code == 404
