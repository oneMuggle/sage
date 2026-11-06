"""``POST /sessions/{id}/wake`` REST 路由单测（2026-11-05）。

独立挂载 router（不导入 backend.main），用 FakeChatService 验证参数分派与
错误映射；Wake 落库行为由 ``test_wake_tool`` / WakeStore 测试覆盖。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.wake_router import build_router
from backend.domain.wake import Wake, WakeKind

FIRE_AT = "2099-01-01T00:00:00+00:00"


class FakeChatService:
    def __init__(self) -> None:
        self.calls: list = []

    async def sleep_for(self, session_id: str, seconds: float, *, note: str = ""):
        self.calls.append(("for", session_id, seconds, note))
        return Wake.create(session_id, WakeKind.TIMER, fire_at=FIRE_AT, note=note)

    async def sleep_until(self, session_id: str, when, *, note: str = ""):
        self.calls.append(("until", session_id, str(when), note))
        if str(when) == "bad-time":
            raise ValueError("invalid ISO-8601 timestamp")
        return Wake.create(session_id, WakeKind.TIMER, fire_at=FIRE_AT, note=note)


def _client(service) -> TestClient:
    app = FastAPI()
    app.include_router(build_router(lambda: service), prefix="/api/v1")
    return TestClient(app)


def test_schedule_wake_with_seconds() -> None:
    svc = FakeChatService()
    resp = _client(svc).post(
        "/api/v1/sessions/sess-1/wake",
        json={"seconds": 600, "note": "检查 CI"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["session_id"] == "sess-1"
    assert body["fire_at"] == FIRE_AT
    assert svc.calls == [("for", "sess-1", 600.0, "检查 CI")]


def test_schedule_wake_with_at() -> None:
    svc = FakeChatService()
    resp = _client(svc).post(
        "/api/v1/sessions/sess-1/wake",
        json={"at": "2099-01-01T00:00:00+08:00"},
    )
    assert resp.status_code == 200
    assert svc.calls[0][0] == "until"


def test_requires_exactly_one_of_seconds_and_at() -> None:
    client = _client(FakeChatService())
    assert client.post("/api/v1/sessions/s/wake", json={}).status_code == 422
    assert (
        client.post(
            "/api/v1/sessions/s/wake",
            json={"seconds": 10, "at": FIRE_AT},
        ).status_code
        == 422
    )


def test_invalid_timestamp_maps_to_422() -> None:
    resp = _client(FakeChatService()).post(
        "/api/v1/sessions/s/wake", json={"at": "bad-time"}
    )
    assert resp.status_code == 422


def test_uninitialised_service_returns_503() -> None:
    resp = _client(None).post("/api/v1/sessions/s/wake", json={"seconds": 10})
    assert resp.status_code == 503
