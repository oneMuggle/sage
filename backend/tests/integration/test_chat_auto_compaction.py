"""
M4 聊天流自动压缩集成测试

/chat/stream producer 在 run_loop 之前检查会话历史：
1. 超阈值 → 先压缩（mock 摘要 LLM + mock SageAgent.run_loop），
   会话最终包含续接标记 + 本轮回复
2. 压缩失败 → 只记日志，聊天照常完成（压缩失败永不阻塞对话）
"""

import asyncio
import contextlib
import time
from unittest.mock import patch

import pytest

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.data.session_repo import Message as DbMessage
from backend.data.session_repo import MessageRepository, SessionRepository
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"
SESSIONS_PATH = "/api/v1/sessions"
DIGEST = "## 目标\n自动压缩集成测试\n## 决策\n无\n## 关键事实\n无\n## 待办事项\n无"


def _seed_over_threshold(session_id: str, n: int = 14) -> None:
    repo = MessageRepository()
    base = int(time.time() * 1000) - 10_000_000  # 远早于本轮消息
    for i in range(n):
        repo.save(
            DbMessage(
                id=f"hist-{i}",
                session_id=session_id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"历史消息内容填充 token 阈值 #{i}" * 3,
                created_at=base + i * 10,
            )
        )


def _mock_run_loop_done(reply: str):
    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(state=AgentState.DONE, iteration=0, content=reply)

    return mock_run_loop


async def _drive_stream(client, session_id: str, message: str) -> None:
    """POST /chat/stream → attach → 等待 producer 跑完。"""
    create_stream = await client.post(
        CHAT_STREAM_PATH, json={"session_id": session_id, "message": message}
    )
    assert create_stream.status_code == 200, create_stream.text
    stream_id = create_stream.json()["streamId"]
    attach = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
    assert attach.status_code == 200
    entry = app.state.streams.get(stream_id)
    if entry and entry.task:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await entry.task


@pytest.mark.asyncio()
async def test_auto_compaction_before_chat_run_loop(client, monkeypatch):
    """超阈值会话发消息 → 历史被压缩 + 续接标记 + 本轮 user/assistant 都在。"""
    monkeypatch.setenv("SAGE_COMPACT_THRESHOLD", "100")

    create = await client.post(SESSIONS_PATH, json={"title": "自动压缩"})
    session_id = create.json()["id"]
    _seed_over_threshold(session_id, n=14)

    async def fake_summary_llm(prompt: str) -> str:
        return DIGEST

    monkeypatch.setattr(
        "backend.api.legacy_routes._build_compaction_llm_callable",
        lambda: fake_summary_llm,
    )

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = _mock_run_loop_done("压缩后的新回复")
        await _drive_stream(client, session_id, "压缩后继续聊天")

    rows = MessageRepository().get_by_session(session_id)
    contents = [r.content for r in rows]

    # 压缩结果: 1 续接 + 6 保留历史
    assert any(c.startswith("[上下文已压缩] 此前对话摘要：") for c in contents)
    assert sum(1 for c in contents if c.startswith("历史消息内容")) == 6
    # 本轮对话正常完成
    assert "压缩后继续聊天" in contents  # user
    assert "压缩后的新回复" in contents  # assistant
    # 总数 = 7 (压缩后) + 2 (本轮) = 9
    assert len(rows) == 9

    sess = SessionRepository().get(session_id)
    assert sess.message_count == 9


@pytest.mark.asyncio()
async def test_auto_compaction_failure_never_blocks_chat(client, monkeypatch):
    """摘要 LLM 爆炸 → 聊天照常完成, 历史保持未压缩。"""
    monkeypatch.setenv("SAGE_COMPACT_THRESHOLD", "100")

    create = await client.post(SESSIONS_PATH, json={"title": "压缩失败不阻塞"})
    session_id = create.json()["id"]
    _seed_over_threshold(session_id, n=14)

    async def exploding_llm(prompt: str) -> str:
        raise RuntimeError("summary upstream down")

    monkeypatch.setattr(
        "backend.api.legacy_routes._build_compaction_llm_callable",
        lambda: exploding_llm,
    )

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = _mock_run_loop_done("照常回复")
        await _drive_stream(client, session_id, "还要聊")

    rows = MessageRepository().get_by_session(session_id)
    contents = [r.content for r in rows]

    # 未压缩: 14 条历史原样 + 本轮 2 条
    assert len(rows) == 16
    assert not any(c.startswith("[上下文已压缩]") for c in contents)
    assert "照常回复" in contents
    assert "还要聊" in contents
