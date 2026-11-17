"""M3 受控浏览器控制面 REST 契约测试（manager 用假会话，不起真实浏览器）。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import List

import pytest

import backend.api.browser_use_routes as routes
from backend.services.browser_control import (
    BrowserControlState,
    get_browser_control,
    reset_browser_control_for_tests,
)

pytestmark = pytest.mark.unit

BASE = "/api/v1/browser/control"


def _fake_session(
    session_id: str,
    browser_type: str = "chrome",
    headless: bool = True,
    alive: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        browser_id=session_id,
        browser_type=browser_type,
        headless=headless,
        is_alive=lambda: alive,
    )


class _FakeManager:
    def __init__(self, sessions: List[SimpleNamespace]) -> None:
        self._sessions = sessions

    def all_sessions(self) -> List[SimpleNamespace]:
        return list(self._sessions)

    def get(self, session_id):
        for session in self._sessions:
            if session.browser_id == session_id:
                return session
        return None


@pytest.fixture()
def control_env(monkeypatch):
    reset_browser_control_for_tests()
    sessions = [
        _fake_session("s1"),
        _fake_session("s2", browser_type="edge", headless=False),
    ]
    manager = _FakeManager(sessions)
    monkeypatch.setattr(routes, "get_browser_manager", lambda: manager)
    yield manager
    reset_browser_control_for_tests()


async def test_list_reports_sessions_with_agent_default(client, control_env):
    resp = await client.get(BASE)
    assert resp.status_code == 200
    assert resp.json() == {
        "sessions": [
            {
                "session_id": "s1",
                "state": "agent",
                "alive": True,
                "browser_type": "chrome",
                "headless": True,
            },
            {
                "session_id": "s2",
                "state": "agent",
                "alive": True,
                "browser_type": "edge",
                "headless": False,
            },
        ]
    }


async def test_list_reflects_paused_state(client, control_env):
    paused = await client.post(f"{BASE}/s1", json={"action": "pause"})
    assert paused.status_code == 200
    resp = await client.get(BASE)
    states = {item["session_id"]: item["state"] for item in resp.json()["sessions"]}
    assert states == {"s1": "paused", "s2": "agent"}


async def test_get_single_known_and_unknown(client, control_env):
    known = await client.get(f"{BASE}/s1")
    assert known.status_code == 200
    assert known.json() == {"session_id": "s1", "state": "agent", "known": True}

    unknown = await client.get(f"{BASE}/ghost")
    assert unknown.status_code == 200
    assert unknown.json() == {"session_id": "ghost", "state": "agent", "known": False}


async def test_registry_only_session_is_known(client, control_env):
    get_browser_control().set_state("s9", BrowserControlState.PAUSED)
    resp = await client.get(f"{BASE}/s9")
    assert resp.json() == {"session_id": "s9", "state": "paused", "known": True}

    resumed = await client.post(f"{BASE}/s9", json={"action": "resume"})
    assert resumed.status_code == 200
    assert resumed.json() == {"session_id": "s9", "state": "agent"}


async def test_post_actions_map_to_states(client, control_env):
    cases = [
        ("pause", "paused"),
        ("takeover", "user_takeover"),
        ("return", "agent"),
        ("resume", "agent"),
    ]
    for action, expected in cases:
        resp = await client.post(f"{BASE}/s1", json={"action": action})
        assert resp.status_code == 200, action
        assert resp.json() == {"session_id": "s1", "state": expected}

    # 大小写/空白容错
    resp = await client.post(f"{BASE}/s1", json={"action": " PAUSE "})
    assert resp.status_code == 200
    assert resp.json()["state"] == "paused"


async def test_invalid_action_returns_400_with_valid_values(client, control_env):
    resp = await client.post(f"{BASE}/s1", json={"action": "dance"})
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert "dance" in body["error"]
    for valid in ("pause", "resume", "takeover", "return"):
        assert valid in body["error"]
    # 非法 action 不改变状态
    assert get_browser_control().get_state("s1") is BrowserControlState.AGENT


async def test_unknown_session_returns_404(client, control_env):
    resp = await client.post(f"{BASE}/ghost", json={"action": "pause"})
    assert resp.status_code == 404
    assert resp.json() == {"ok": False, "error": "session_not_found"}


async def test_missing_action_body_is_rejected(client, control_env):
    resp = await client.post(f"{BASE}/s1", json={})
    assert resp.status_code == 422


async def test_origin_guard_rejects_foreign_origin(client, control_env):
    headers = {"Origin": "https://evil.example"}
    listed = await client.get(BASE, headers=headers)
    assert listed.status_code == 403
    assert listed.json() == {"ok": False, "error": "forbidden_origin"}

    posted = await client.post(f"{BASE}/s1", json={"action": "pause"}, headers=headers)
    assert posted.status_code == 403
    assert get_browser_control().get_state("s1") is BrowserControlState.AGENT
