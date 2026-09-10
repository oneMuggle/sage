"""技能 pin（防归档）单元测试（Round 5）"""

from __future__ import annotations

import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.legacy_routes import router
from backend.data.database import Database
from backend.skills.lifecycle import SkillLifecycleStore

pytestmark = pytest.mark.unit


@pytest.fixture()
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
        yield db
        db.close()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, headers={"Authorization": "Bearer test-local-auth-token"})


class TestPinStore:
    def test_set_and_query(self, tmp_db):
        store = SkillLifecycleStore(db=tmp_db)
        assert store.is_pinned("a") is False
        store.set_pinned("a", True)
        assert store.is_pinned("a") is True
        assert store.get_pinned_names() == {"a"}
        store.set_pinned("a", False)
        assert store.get_pinned_names() == set()

    def test_pin_idempotent(self, tmp_db):
        store = SkillLifecycleStore(db=tmp_db)
        store.set_pinned("a", True)
        store.set_pinned("a", True)
        assert store.get_pinned_names() == {"a"}


class TestArchivePinGuard:
    def test_archive_pinned_skill_conflict(self, tmp_db, client, monkeypatch):
        """pinned 技能 → archive 409 skill_pinned"""
        from unittest.mock import MagicMock

        store = SkillLifecycleStore(db=tmp_db)
        monkeypatch.setattr(
            "backend.skills.lifecycle.get_lifecycle_store", lambda: store
        )
        # 路由内部 from ... import get_lifecycle_store（函数内导入）→ 补一个补丁点
        import backend.skills.lifecycle as lifecycle_mod

        monkeypatch.setattr(
            lifecycle_mod, "get_lifecycle_store", lambda: store, raising=True
        )
        # adapter 打桩：set_archived 恒成功（guard 应先行拦截，不应触达）
        adapter = MagicMock()
        adapter.set_archived.return_value = True
        adapter.list_skills_extended.return_value = [{"name": "guarded"}]
        monkeypatch.setattr(
            "backend.api.legacy_routes._get_skill_adapter", lambda: adapter
        )

        store.set_pinned("guarded", True)
        resp = client.post("/skills/guarded/archive", json={"archived": True})
        assert resp.status_code == 409
        assert resp.json()["detail"]["type"] == "skill_pinned"
        adapter.set_archived.assert_not_called()

    def test_pin_endpoint_roundtrip(self, tmp_db, client, monkeypatch):
        """pin → archive 409 → unpin → archive 放行"""
        from unittest.mock import MagicMock

        store = SkillLifecycleStore(db=tmp_db)
        import backend.skills.lifecycle as lifecycle_mod

        monkeypatch.setattr(lifecycle_mod, "get_lifecycle_store", lambda: store)
        adapter = MagicMock()
        adapter.set_archived.return_value = True
        adapter.list_skills_extended.return_value = [{"name": "p"}]
        adapter.is_enabled.return_value = True
        adapter.usage_count.return_value = 0
        monkeypatch.setattr(
            "backend.api.legacy_routes._get_skill_adapter", lambda: adapter
        )

        resp = client.post("/skills/p/pin", json={"pinned": True})
        assert resp.status_code == 200
        assert resp.json() == {"name": "p", "pinned": True}

        resp = client.post("/skills/p/archive", json={"archived": True})
        assert resp.status_code == 409

        client.post("/skills/p/pin", json={"pinned": False})
        resp = client.post("/skills/p/archive", json={"archived": True})
        assert resp.status_code == 200
