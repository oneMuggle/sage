"""M3 受控浏览器控制面 REST 契约测试（manager 用假会话，不起真实浏览器）。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import List

import pytest

import backend.api.browser_use_routes as routes
from backend.data import browser_action_repo
from backend.services import browser_safety
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


# ---------------------------------------------------------------------------
# M4：使用偏好 / 站点策略 / 待确认 / 审计
# ---------------------------------------------------------------------------

BASE_M4 = "/api/v1/browser"


@pytest.fixture()
def safety_env():
    browser_safety.reset_confirmations_for_tests()
    browser_safety.reset_site_policies_for_tests()
    reset_browser_control_for_tests()
    yield browser_safety.get_confirmation_registry()
    browser_safety.reset_confirmations_for_tests()
    browser_safety.reset_site_policies_for_tests()
    reset_browser_control_for_tests()


def _create_site_confirmation(
    session_id="s1", domain="example.com", fingerprint="fp-site", conversation=""
):
    return browser_safety.get_confirmation_registry().create(
        session_id,
        "site_access",
        code="site_access",
        domain=domain,
        description=f"访问站点 {domain}",
        options=list(browser_safety.SITE_ACCESS_OPTIONS),
        fingerprint=fingerprint,
        conversation_id=conversation,
    )


def _create_action_confirmation(session_id="s1", fingerprint="fp-action", conversation=""):
    return browser_safety.get_confirmation_registry().create(
        session_id,
        "sensitive_action",
        code="sensitive_submit",
        domain="example.com",
        description="提交订单",
        options=list(browser_safety.SENSITIVE_ACTION_OPTIONS),
        fingerprint=fingerprint,
        conversation_id=conversation,
    )


async def test_use_config_defaults_and_put_persists(client, safety_env):
    initial = await client.get(f"{BASE_M4}/use-config")
    assert initial.status_code == 200
    assert initial.json() == {"default_visible": True, "step_thumbnails": True}

    updated = await client.put(
        f"{BASE_M4}/use-config", json={"step_thumbnails": False}
    )
    assert updated.status_code == 200
    assert updated.json() == {"default_visible": True, "step_thumbnails": False}

    reread = await client.get(f"{BASE_M4}/use-config")
    assert reread.json() == {"default_visible": True, "step_thumbnails": False}

    # 空 body 不改变任何字段
    noop = await client.put(f"{BASE_M4}/use-config", json={})
    assert noop.status_code == 200
    assert noop.json() == {"default_visible": True, "step_thumbnails": False}


async def test_use_config_rejects_unknown_fields(client, safety_env):
    resp = await client.put(f"{BASE_M4}/use-config", json={"surprise": True})
    assert resp.status_code == 422


async def test_site_policies_list_put_delete(client, safety_env):
    empty = await client.get(f"{BASE_M4}/site-policies")
    assert empty.status_code == 200
    assert empty.json() == {"policies": []}

    put = await client.put(
        f"{BASE_M4}/site-policies/Example.com", json={"mode": "allow"}
    )
    assert put.status_code == 200
    body = put.json()
    assert body["domain"] == "example.com"
    assert body["mode"] == "allow"
    assert body["updated_at"] > 0

    listed = await client.get(f"{BASE_M4}/site-policies")
    assert [item["domain"] for item in listed.json()["policies"]] == ["example.com"]

    deleted = await client.delete(f"{BASE_M4}/site-policies/example.com")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True, "domain": "example.com"}

    again = await client.delete(f"{BASE_M4}/site-policies/example.com")
    assert again.status_code == 404
    assert again.json() == {"ok": False, "error": "policy_not_found"}


async def test_site_policy_put_rejects_invalid_mode(client, safety_env):
    resp = await client.put(f"{BASE_M4}/site-policies/example.com", json={"mode": "maybe"})
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


async def test_confirmations_list_and_approve(client, control_env, safety_env):
    pending = _create_action_confirmation()
    get_browser_control().set_state("s1", BrowserControlState.PAUSED)

    listed = await client.get(f"{BASE_M4}/confirmations", params={"session_id": "s1"})
    assert listed.status_code == 200
    items = listed.json()["confirmations"]
    assert [item["id"] for item in items] == [pending.id]
    assert "fingerprint" not in items[0]
    assert items[0]["options"] == ["approve", "deny"]

    approved = await client.post(
        f"{BASE_M4}/confirmations/{pending.id}", json={"decision": "approve"}
    )
    assert approved.status_code == 200
    assert approved.json() == {
        "confirmation_id": pending.id,
        "kind": "sensitive_action",
        "decision": "approve",
        "control_state": "agent",
    }
    assert get_browser_control().get_state("s1") is BrowserControlState.AGENT
    assert browser_safety.get_confirmation_registry().consume_approval(
        "fp-action"
    ) is True
    # 重复裁决：待确认项已被移除
    again = await client.post(
        f"{BASE_M4}/confirmations/{pending.id}", json={"decision": "approve"}
    )
    assert again.status_code == 404


async def test_confirmation_deny_registers_denial(client, control_env, safety_env):
    pending = _create_action_confirmation()

    denied = await client.post(
        f"{BASE_M4}/confirmations/{pending.id}", json={"decision": "deny"}
    )
    assert denied.status_code == 200
    assert denied.json()["decision"] == "deny"
    assert browser_safety.get_confirmation_registry().is_denied("fp-action") is True


async def test_site_confirmation_always_grants_persistent_allow(
    client, control_env, safety_env
):
    pending = _create_site_confirmation()

    resp = await client.post(
        f"{BASE_M4}/confirmations/{pending.id}", json={"decision": "always"}
    )
    assert resp.status_code == 200
    assert browser_safety.check_site("other-session", "https://example.com/") == "allow"


async def test_site_confirmation_session_grants_only_that_session(
    client, control_env, safety_env
):
    pending = _create_site_confirmation(session_id="s1")

    resp = await client.post(
        f"{BASE_M4}/confirmations/{pending.id}", json={"decision": "session"}
    )
    assert resp.status_code == 200
    assert browser_safety.check_site("s1", "https://example.com/") == "allow"
    assert browser_safety.check_site("s2", "https://example.com/") == "confirm"


async def test_confirmation_validation_errors(client, control_env, safety_env):
    action_pending = _create_action_confirmation()

    invalid_decision = await client.post(
        f"{BASE_M4}/confirmations/{action_pending.id}", json={"decision": "maybe"}
    )
    assert invalid_decision.status_code == 400
    assert "maybe" in invalid_decision.json()["error"]

    # approve 不适用于 site_access（合法值为 session|always|deny）
    site_pending = _create_site_confirmation()
    wrong_kind = await client.post(
        f"{BASE_M4}/confirmations/{site_pending.id}", json={"decision": "approve"}
    )
    assert wrong_kind.status_code == 400

    unknown = await client.post(
        f"{BASE_M4}/confirmations/ghost", json={"decision": "approve"}
    )
    assert unknown.status_code == 404
    assert unknown.json() == {"ok": False, "error": "confirmation_not_found"}


async def test_confirmations_list_filters_by_conversation(client, safety_env):
    mine = _create_action_confirmation(conversation="c1")
    other = _create_action_confirmation(fingerprint="fp-other", conversation="c2")
    http = _create_site_confirmation(
        session_id="", fingerprint="fp-http", conversation="c1"
    )

    by_conversation = await client.get(
        f"{BASE_M4}/confirmations", params={"conversation_id": "c1"}
    )
    assert by_conversation.status_code == 200
    items = by_conversation.json()["confirmations"]
    assert [item["id"] for item in items] == [mine.id, http.id]
    assert {item["conversation_id"] for item in items} == {"c1"}

    # 旧语义：只按 session 过滤仍可用
    by_session = await client.get(
        f"{BASE_M4}/confirmations", params={"session_id": "s1"}
    )
    ids = {item["id"] for item in by_session.json()["confirmations"]}
    assert ids == {mine.id, other.id}


async def test_confirmation_resolve_requires_matching_conversation(
    client, control_env, safety_env
):
    pending = _create_action_confirmation(conversation="c1")

    missing = await client.post(
        f"{BASE_M4}/confirmations/{pending.id}", json={"decision": "approve"}
    )
    assert missing.status_code == 404
    assert missing.json() == {"ok": False, "error": "confirmation_not_found"}
    assert browser_safety.get_confirmation_registry().get(pending.id) is not None

    mismatch = await client.post(
        f"{BASE_M4}/confirmations/{pending.id}",
        json={"decision": "approve", "conversation_id": "c2"},
    )
    assert mismatch.status_code == 404
    assert browser_safety.get_confirmation_registry().get(pending.id) is not None

    matched = await client.post(
        f"{BASE_M4}/confirmations/{pending.id}",
        json={"decision": "approve", "conversation_id": "c1"},
    )
    assert matched.status_code == 200
    assert matched.json()["confirmation_id"] == pending.id


async def test_confirmation_resolve_legacy_item_without_conversation(
    client, control_env, safety_env
):
    pending = _create_action_confirmation()

    resp = await client.post(
        f"{BASE_M4}/confirmations/{pending.id}",
        json={"decision": "approve", "conversation_id": "c1"},
    )
    assert resp.status_code == 200


async def test_audit_lists_recent_filtered_by_session(client, safety_env):
    browser_action_repo.record(
        {
            "session_id": "s1",
            "ts": 1737000000000,
            "domain": "example.com",
            "tool": "browser_navigate",
            "action": "navigate",
            "result": "ok",
            "approval": "auto",
            "duration_ms": 5,
        }
    )
    browser_action_repo.record(
        {
            "session_id": "s2",
            "ts": 1737000001000,
            "domain": "other.example",
            "tool": "browser_interact",
            "action": "click",
            "result": "blocked",
            "approval": "none",
            "duration_ms": 1,
        }
    )

    mine = await client.get(f"{BASE_M4}/audit", params={"session_id": "s1"})
    assert mine.status_code == 200
    entries = mine.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["tool"] == "browser_navigate"
    assert entries[0]["domain"] == "example.com"

    everything = await client.get(f"{BASE_M4}/audit", params={"limit": 10})
    assert len(everything.json()["entries"]) == 2


async def test_m4_origin_guard(client, control_env, safety_env):
    headers = {"Origin": "https://evil.example"}

    config = await client.get(f"{BASE_M4}/use-config", headers=headers)
    assert config.status_code == 403
    assert config.json() == {"ok": False, "error": "forbidden_origin"}

    policy = await client.put(
        f"{BASE_M4}/site-policies/example.com", json={"mode": "allow"}, headers=headers
    )
    assert policy.status_code == 403

    audit = await client.get(f"{BASE_M4}/audit", headers=headers)
    assert audit.status_code == 403


async def test_confirmation_resolve_does_not_steal_active_takeover(
    client, control_env, safety_env
):
    """最终修复：迟到的确认裁决只在 PAUSED 时恢复 AGENT，不得夺回用户接管。"""
    pending = _create_action_confirmation()
    get_browser_control().set_state("s1", BrowserControlState.USER_TAKEOVER)

    resp = await client.post(
        f"{BASE_M4}/confirmations/{pending.id}", json={"decision": "approve"}
    )

    assert resp.status_code == 200
    assert resp.json()["control_state"] == "user_takeover"
    assert get_browser_control().get_state("s1") is BrowserControlState.USER_TAKEOVER
