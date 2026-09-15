"""R28: /skills/consolidation/scan 的 mode=auto 增量巡检路由测试。

mock consolidator 的服务与候选收集函数，验证：
- mode=full（缺省）→ 全量收集（names=None）
- mode=auto 且无水位 → 退化全量
- mode=auto 且有水位 → 以 collect_delta_names 的结果为候选
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.legacy_routes import router
from backend.skills import consolidator

pytestmark = pytest.mark.unit


class _FakeService:
    """无 LLM 依赖的巡检服务桩。"""

    def __init__(self) -> None:
        self.scan = AsyncMock(return_value=[{"type": "revise", "skill_names": ["a"], "reason": "r"}])
        self.generate_drafts = AsyncMock(return_value=0)


@pytest.fixture()
def scan_env(monkeypatch):
    """打桩 consolidator 模块属性；返回 (captured, service, setters)。"""
    captured: dict = {}
    service = _FakeService()

    def fake_collect(names=None):
        captured["names"] = names
        return [{"name": "a", "description": "A", "when_to_use": "", "usage_count": 1}]

    monkeypatch.setattr(consolidator, "get_consolidation_service", lambda: service)
    monkeypatch.setattr(consolidator, "collect_active_skills", fake_collect)
    monkeypatch.setattr(consolidator, "collect_skill_docs", lambda names: {})

    def set_watermark(value):
        monkeypatch.setattr(consolidator, "last_scan_watermark", lambda: value)

    def set_delta(delta):
        monkeypatch.setattr(consolidator, "collect_delta_names", lambda wm: delta)

    return captured, service, set_watermark, set_delta


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, headers={"Authorization": "Bearer test-local-auth-token"})


class TestScanModes:
    def test_default_mode_is_full(self, client, scan_env, monkeypatch):
        captured, _, set_watermark, set_delta = scan_env
        set_watermark(12345)
        set_delta({"delta-skill"})

        resp = client.post("/skills/consolidation/scan?auto_draft=false")
        assert resp.status_code == 200
        assert resp.json()["mode"] == "full"
        assert captured["names"] is None  # 全量：不过滤候选

    def test_auto_mode_with_watermark_scans_delta(self, client, scan_env):
        captured, _, set_watermark, set_delta = scan_env
        set_watermark(12345)
        set_delta({"delta-skill"})

        resp = client.post("/skills/consolidation/scan?auto_draft=false&mode=auto")
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "auto"
        assert captured["names"] == {"delta-skill"}

    def test_auto_mode_without_watermark_falls_back_to_full(self, client, scan_env):
        captured, _, set_watermark, _set_delta = scan_env
        set_watermark(None)

        resp = client.post("/skills/consolidation/scan?auto_draft=false&mode=auto")
        assert resp.status_code == 200
        assert resp.json()["mode"] == "auto"
        assert captured["names"] is None  # 无水位 → 退化全量

    def test_unknown_mode_treated_as_full(self, client, scan_env):
        captured, _, set_watermark, set_delta = scan_env
        set_watermark(12345)
        set_delta({"delta-skill"})

        resp = client.post("/skills/consolidation/scan?auto_draft=false&mode=bogus")
        assert resp.status_code == 200
        assert resp.json()["mode"] == "full"
        assert captured["names"] is None
