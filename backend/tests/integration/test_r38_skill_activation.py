"""R38 技能激活透明度 —— legacy 流端到端回归测试 (MEDIUM-1 / MEDIUM-3)。

缺陷背景：初版用 ``getattr(agent, "skills", None)`` 取技能端口，而
``SageAgent`` 无 ``skills`` 属性 → 恒 ``None`` → ``_skill_activation_block()``
立即返回空，技能激活**永不生效**（MEDIUM-1）；且即便生效，
``triggers_matched`` 也因 ``_matches()`` 塌缩成 bool 而恒为空数组（MEDIUM-3）。

本文件在 ``_get_skill_adapter`` 接缝上打桩，驱动真实 ``/chat/stream``：

1. 命中技能时 context_block 进入下发 LLM 的 system 消息；
2. 流中出现 ``skill_activated`` 事件，且 ``triggers_matched`` 非空；
3. 用户消息行落库时带 ``activated_skills``。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Optional
from unittest.mock import patch

import pytest

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.data.session_repo import MessageRepository
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"
SESSIONS_PATH = "/api/v1/sessions"


class _FakeActivationResult:
    """模拟 InprocSkillAdapter.auto_activate 的返回对象。"""

    def __init__(self) -> None:
        self.names = ("demo-skill",)
        self.context_block = "# 技能：demo-skill\n按部署流程操作。"
        self.matches = {"demo-skill": ("部署", "上线")}


class _FakeSkillAdapter:
    """唯一实现 auto_activate 扩展方法的端口形状。"""

    def auto_activate(self, message: str) -> _FakeActivationResult:
        return _FakeActivationResult()


class _NoAutoActivateAdapter:
    """无 auto_activate 的端口 → 结构性探测应降级为空。"""


def _mock_run_loop_done(reply: str, captured: Optional[dict] = None):
    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        if captured is not None:
            captured["messages"] = messages
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(state=AgentState.DONE, iteration=0, content=reply)

    return mock_run_loop


async def _drive_stream(client, session_id: str, message: str) -> list[dict]:
    """POST /chat/stream → attach → 等 producer 跑完 → 解析 NDJSON 事件。"""
    create = await client.post(
        CHAT_STREAM_PATH, json={"session_id": session_id, "message": message}
    )
    assert create.status_code == 200, create.text
    stream_id = create.json()["streamId"]
    attach = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
    assert attach.status_code == 200
    entry = app.state.streams.get(stream_id)
    if entry and entry.task:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await entry.task
    return [json.loads(line) for line in attach.text.split("\n") if line.strip()]


@pytest.mark.asyncio()
async def test_skill_activated_event_carries_matched_triggers(client):
    """命中技能 → 流中 skill_activated 事件带真实命中触发词。"""
    create = await client.post(SESSIONS_PATH, json={"title": "R38 技能激活"})
    session_id = create.json()["id"]

    captured: dict = {}
    with patch(
        "backend.api.legacy_skills_routes._get_skill_adapter",
        return_value=_FakeSkillAdapter(),
    ), patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = _mock_run_loop_done("已完成部署", captured)
        events = await _drive_stream(client, session_id, "帮我部署一下")

    # TM2 (DSH 对标 R11): 过滤 context_pressure 事件（非 ReAct 流程事件）
    non_cp = [e for e in events if e.get("state") != "context_pressure"]
    skill_events = [e for e in non_cp if e.get("state") == "skill_activated"]
    assert len(skill_events) == 1, f"期望 1 个 skill_activated, 实得 {events}"
    skills = skill_events[0]["skills"]
    assert skills == [
        {"name": "demo-skill", "triggers_matched": ["部署", "上线"]}
    ], f"triggers_matched 应为真实命中词, 实得 {skills}"

    # (a) context_block 进入下发 LLM 的 system 消息
    sent = captured.get("messages")
    assert sent, "run_loop 未被调用"
    system_text = "\n".join(
        m.content if hasattr(m, "content") else str(m) for m in sent
    )
    assert "按部署流程操作" in system_text, "技能 body 未进入 system prompt"

    # (c) 用户消息行落库带 activated_skills
    rows = MessageRepository().get_by_session(session_id)
    user_row = next(r for r in rows if r.role == "user")
    parsed = user_row.to_dict()["activated_skills"]
    assert parsed == [{"name": "demo-skill", "triggers_matched": ["部署", "上线"]}]


@pytest.mark.asyncio()
async def test_no_skill_event_when_port_lacks_auto_activate(client):
    """端口无 auto_activate（纯 SkillPort）→ 不推事件、不落 activated_skills。"""
    create = await client.post(SESSIONS_PATH, json={"title": "R38 无激活"})
    session_id = create.json()["id"]

    with patch(
        "backend.api.legacy_skills_routes._get_skill_adapter",
        return_value=_NoAutoActivateAdapter(),
    ), patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = _mock_run_loop_done("好的")
        events = await _drive_stream(client, session_id, "随便聊聊")

    assert not [e for e in events if e.get("state") == "skill_activated"]

    rows = MessageRepository().get_by_session(session_id)
    user_row = next(r for r in rows if r.role == "user")
    assert user_row.to_dict()["activated_skills"] is None


@pytest.mark.asyncio()
async def test_skill_port_failure_never_blocks_chat(client):
    """技能端口抛错 → 只跳过激活，聊天照常完成（fail-safe 铁律）。"""
    create = await client.post(SESSIONS_PATH, json={"title": "R38 fail-safe"})
    session_id = create.json()["id"]

    class _ExplodingAdapter:
        def auto_activate(self, message: str):
            raise RuntimeError("skill discovery blew up")

    with patch(
        "backend.api.legacy_skills_routes._get_skill_adapter",
        return_value=_ExplodingAdapter(),
    ), patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = _mock_run_loop_done("照常回复")
        events = await _drive_stream(client, session_id, "触发爆炸")

    assert any(e.get("state") == "done" for e in events), f"流未正常结束: {events}"
    rows = MessageRepository().get_by_session(session_id)
    assert any(r.content == "照常回复" for r in rows)
