"""
Recap 路由 API 测试 — POST /api/v1/chat/recap

真实临时 DB（conftest autouse fixture）+ monkeypatch 的 LLM callable：
- 成功路径: 返回 camelCase recap 信封
- 未知会话 404
- 无 LLM 配置 502 llm_not_configured
- 消息不足 200 + {ok: false, reason: "too_short"}
- LLM 失败 502 recap_failed
"""

import time

import pytest

from backend.data.session_repo import (
    Message as DbMessage,
    MessageRepository,
    SessionRepository,
)

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"


def _seed_session(n: int) -> str:
    sess = SessionRepository().create(title="recap 测试会话")
    repo = MessageRepository()
    base = int(time.time() * 1000)
    for i in range(n):
        repo.save(
            DbMessage(
                id=f"recap-seed-{i}",
                session_id=sess.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"这是一条用于 recap 测试的消息 #{i}",
                created_at=base + i * 10,
            )
        )
    return sess.id


def _patch_llm(monkeypatch, callable_):
    monkeypatch.setattr(
        "backend.api.legacy_chat_routes._build_compaction_llm_callable",
        lambda: callable_,
    )


async def _fake_llm_ok(prompt: str) -> str:
    return (
        '{"progress": "完成认证模块", "decisions": ["用 JWT"], '
        '"nextSteps": ["写测试"], "openQuestions": ["要 OAuth 吗"]}'
    )


@pytest.mark.asyncio()
async def test_recap_unknown_session_returns_404(client):
    resp = await client.post(f"{PREFIX}/chat/recap", json={"session_id": "nonexistent-id"})
    assert resp.status_code == 404


@pytest.mark.asyncio()
async def test_recap_without_llm_config_returns_502(client, monkeypatch):
    session_id = _seed_session(4)
    _patch_llm(monkeypatch, None)

    resp = await client.post(f"{PREFIX}/chat/recap", json={"session_id": session_id})

    assert resp.status_code == 502
    data = resp.json()
    assert data["ok"] is False
    assert data["error"] == "llm_not_configured"


@pytest.mark.asyncio()
async def test_recap_too_short_returns_reason(client, monkeypatch):
    session_id = _seed_session(2)
    _patch_llm(monkeypatch, _fake_llm_ok)

    resp = await client.post(f"{PREFIX}/chat/recap", json={"session_id": session_id})

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["reason"] == "too_short"


@pytest.mark.asyncio()
async def test_recap_success_returns_camel_case_payload(client, monkeypatch):
    session_id = _seed_session(4)
    _patch_llm(monkeypatch, _fake_llm_ok)

    resp = await client.post(f"{PREFIX}/chat/recap", json={"session_id": session_id})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "ok": True,
        "recap": {
            "progress": "完成认证模块",
            "decisions": ["用 JWT"],
            "nextSteps": ["写测试"],
            "openQuestions": ["要 OAuth 吗"],
        },
    }


@pytest.mark.asyncio()
async def test_recap_llm_failure_returns_502(client, monkeypatch):
    session_id = _seed_session(4)

    async def _broken_llm(prompt: str) -> str:
        raise RuntimeError("upstream exploded")

    _patch_llm(monkeypatch, _broken_llm)

    resp = await client.post(f"{PREFIX}/chat/recap", json={"session_id": session_id})

    assert resp.status_code == 502
    data = resp.json()
    assert data["ok"] is False
    assert data["error"] == "recap_failed"
