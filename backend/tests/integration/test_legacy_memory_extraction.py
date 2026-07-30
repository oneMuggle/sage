"""WS-C P0-2: legacy /chat/stream 统一记忆写入路径集成测试

回归缺陷：legacy /chat/stream producer 持久化 user/assistant 消息后
**不触发** MemoryExtractor，只有 hex ChatService.run_turn 写记忆，
导致一半对话数据不进记忆系统。

修复后：producer 在 assistant 消息落盘成功后 best-effort 调用
``chat_service.extract_and_store_memory``（与 hex 路径共用的模块级
函数），受 app_settings.autoMemory 开关控制（缺省 True，与前端
默认值及 hex 路径"有 memory 即写"的行为一致）。

覆盖：
1. mock LLM 走完 /chat/stream 端到端 → memories_episodic 出现提取条目
   （接线不变性：assistant 落盘后才触发提取）
2. autoMemory=false → 不写入
3. 提取过程抛错 → 流照常完成, 不写记忆（best-effort 不破坏流式响应）
"""

import asyncio
import contextlib
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.data.database import get_database
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"

# 提取器 mock 固定返回的事实（绕过真实 LLM 提取）
_FIXED_FACTS = [
    {
        "content": "用户喜欢吃火锅",
        "importance": 7,
        "category": "preference",
        "tags": ["preference"],
    }
]


async def _run_chat_stream(client, session_id: str, message: str) -> str:
    """POST /chat/stream + attach 消费 + 等 producer 跑完，返回 attach 响应文本。"""

    # mock SageAgent.run_loop 直接 DONE（不调真实 LLM）
    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.DONE,
            iteration=0,
            content="好的,我记住了,您喜欢吃火锅。成都的火锅店确实很多,我可以给您推荐几家口碑不错的。",
        )

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        create_stream = await client.post(
            CHAT_STREAM_PATH,
            json={"session_id": session_id, "message": message},
        )
        assert create_stream.status_code == 200, create_stream.text
        stream_id = create_stream.json()["streamId"]

        attach = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
        assert attach.status_code == 200

        # 等 producer 后台 task 完整跑完（落盘 + 记忆提取都在 producer 内）
        entry = app.state.streams.get(stream_id)
        if entry and entry.task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await entry.task

    return attach.text


def _episodic_rows() -> list:
    conn = get_database().get_connection()
    return conn.execute(
        "SELECT content, session_id FROM memories_episodic WHERE is_valid = 1"
    ).fetchall()


@pytest.mark.asyncio()
async def test_legacy_chat_stream_extracts_memory_after_assistant_persisted(client):
    """一次成功 chat 后 memories_episodic 出现提取条目（autoMemory 缺省 True）。"""
    session_id = str(uuid.uuid4())
    user_message = "我特别喜欢吃火锅,尤其是四川麻辣口味的,以后请多给我推荐火锅店"

    # mock 掉 MemoryExtractor.extract（类方法级 patch）：
    # helper 在调用点才 from backend.memory.extractor import MemoryExtractor,
    # patch 类属性后实例化拿到的就是 mock 版 extract, 其余链路
    # （MemoryAdapter.store → MemoryManager.memorize → episodic.save）全部走真实实现。
    with patch(
        "backend.memory.extractor.MemoryExtractor.extract",
        new=AsyncMock(return_value=_FIXED_FACTS),
    ) as mock_extract:
        attach_text = await _run_chat_stream(client, session_id, user_message)

    # 流正常完成
    assert '"state": "done"' in attach_text or '"state":"done"' in attach_text

    # 提取被触发, 且传入的就是本轮 user / assistant 文本
    mock_extract.assert_awaited()
    extract_kwargs = mock_extract.await_args[1]
    assert extract_kwargs["user_message"] == user_message
    assert "火锅" in extract_kwargs["assistant_message"]

    # memories_episodic 出现提取条目, 且行级 session_id 已落表
    # (WS-A 修复 MemoryManager.memorize 的 session_id 透传后启用此断言)
    rows = _episodic_rows()
    matched = [r for r in rows if "用户喜欢吃火锅" in r["content"]]
    assert matched, (
        f"memories_episodic 未出现提取条目: {[dict(r) for r in rows]}"
    )
    assert any(
        r["session_id"] == session_id for r in matched
    ), f"提取条目行级 session_id 未落表: {[dict(r) for r in matched]}"


@pytest.mark.asyncio()
async def test_legacy_chat_stream_skips_extraction_when_auto_memory_disabled(client):
    """app_settings.autoMemory=false 时不写记忆。"""
    from backend.data.settings_repo import SettingsRepository

    SettingsRepository().set_json("app_settings", {"autoMemory": False})

    session_id = str(uuid.uuid4())
    with patch(
        "backend.memory.extractor.MemoryExtractor.extract",
        new=AsyncMock(return_value=_FIXED_FACTS),
    ) as mock_extract:
        attach_text = await _run_chat_stream(client, session_id, "我喜欢吃火锅, 请记住这一点")

    assert '"state": "done"' in attach_text or '"state":"done"' in attach_text
    mock_extract.assert_not_awaited()
    assert _episodic_rows() == []


@pytest.mark.asyncio()
async def test_legacy_chat_stream_extraction_failure_does_not_break_stream(client):
    """提取过程抛错只 warning：流照常完成, 不写记忆, 不 500。"""
    session_id = str(uuid.uuid4())
    with patch(
        "backend.memory.extractor.MemoryExtractor.extract",
        new=AsyncMock(side_effect=RuntimeError("extractor boom")),
    ):
        attach_text = await _run_chat_stream(client, session_id, "我喜欢吃火锅, 请记住这一点")

    # 流未被记忆提取错误打断
    assert '"state": "done"' in attach_text or '"state":"done"' in attach_text
    assert "RuntimeError" not in attach_text
    assert _episodic_rows() == []


@pytest.mark.asyncio()
async def test_legacy_chat_stream_assistant_persist_failure_skips_extraction(client):
    """assistant 落盘失败时不触发提取（不产生无对应消息的脏记忆）。"""
    session_id = str(uuid.uuid4())

    with (
        patch(
            "backend.memory.extractor.MemoryExtractor.extract",
            new=AsyncMock(return_value=_FIXED_FACTS),
        ) as mock_extract,
        patch("backend.api.legacy_routes.MessageRepository") as MockMsgRepo,
    ):
        # 第一次 save(user) 成功, 第二次 save(assistant) 抛错
        MockMsgRepo.return_value.save.side_effect = [None, RuntimeError("simulated db down")]
        attach_text = await _run_chat_stream(client, session_id, "我喜欢吃火锅, 请记住这一点")

    # 流仍正常完成（持久化失败只 warning）
    assert '"state": "done"' in attach_text or '"state":"done"' in attach_text
    # assistant 未落盘 → 提取不应触发
    mock_extract.assert_not_awaited()
    assert _episodic_rows() == []
