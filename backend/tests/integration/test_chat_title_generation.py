"""Phase 5 集成测试 —— 标题生成 + 事件链路 + 回补机制。

覆盖 ``docs/plans/2026-10-27_session-title-optimization.md`` Phase 5.1：

- ``TitleGenerator`` 永不返回 None（LLM 失败走启发式，无 LLM 也走启发式）
- ``fallback_title`` / ``needs_title`` 行为矩阵
- ``MemoryStorageAdapter`` 支持 ``title_attempts`` 字段（hex 路径依赖）
- ``TitleBackfill`` 跨真实 SQLite repo 批量回补历史未命名会话
- ``/api/v1/chat/stream`` legacy 路径发出 ``title_updated`` NDJSON 事件 +
  ``title_pending`` 标记 + 落库 title / title_attempts（事件链路闭环）

注：hex 路径（``ChatService.run_turn`` 内 step 9）的标题生成嵌套在
``if self.memory:`` 块内（与记忆提取共享生命周期），真实桌面端不走该路径
（桌面端经 ``/api/v1/chat/stream`` → legacy_routes）。故事件链路测试集中在
legacy 路径；hex 路径由 TitleGenerator 直接测试覆盖。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sage_core import Message as CoreMessage, Role

from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
from backend.chat.title_generator import (
    DEFAULT_TITLE,
    TitleGenerator,
    fallback_title,
    needs_title,
)
from backend.data.session_repo import Message as RepoMessage, MessageRepository, SessionRepository
from backend.main import app
from backend.scheduler.title_backfill import TitleBackfill

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# LLM 桩件
# --------------------------------------------------------------------------- #


class _RaisingLLM:
    """LLM 桩：每次 chat() 都抛异常 —— 用于测试 LLM 失败路径。"""

    async def chat(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("upstream unavailable")


class _StableTitleLLM:
    """LLM 桩：稳定返回固定标题文本。"""

    def __init__(self, title: str = "数据库事务一致性") -> None:
        self._title = title
        self.calls: List[Dict[str, Any]] = []

    async def chat(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append({"args": args, "kwargs": kwargs})

        class _Resp:
            content = self._title

        return _Resp()


# --------------------------------------------------------------------------- #
# TitleGenerator 直接测试
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio()
async def test_title_generator_returns_llm_title_when_available():
    """LLM 可用且输出合格 → generate() 返回 LLM 标题。"""
    gen = TitleGenerator(_StableTitleLLM("数据库事务一致性"))
    title = await gen.generate("帮我解释一下 ACID 四大特性", "ACID 是指…")
    assert title == "数据库事务一致性"


@pytest.mark.asyncio()
async def test_title_generator_falls_back_when_llm_raises():
    """LLM 抛异常 → generate() 降级到启发式，永不返回 None。"""
    gen = TitleGenerator(_RaisingLLM())
    title = await gen.generate("帮我分析这份 CSV 文件的数据分布情况", "好的，这是分析结果…")
    assert isinstance(title, str)
    assert title  # 非空


@pytest.mark.asyncio()
async def test_title_generator_uses_heuristic_when_llm_is_none():
    """llm_client=None → 直接走启发式。"""
    gen = TitleGenerator(None)
    title = await gen.generate("Python 异步编程的常见陷阱", "asyncio.create_task 要注意…")
    assert isinstance(title, str)
    assert title == "Python 异步编程的常见陷阱"  # 未超 20 字符，原样保留


@pytest.mark.asyncio()
async def test_title_generator_heuristic_short_content():
    """user + assistant 总字符 < MIN_CONTENT_FOR_LLM → 跳过 LLM。"""
    # 即使给了 LLM，短内容也会直接走启发式
    gen = TitleGenerator(_StableTitleLLM("ignored-title"))
    title = await gen.generate("好", "谢")  # combined len = 2
    assert isinstance(title, str)


# --------------------------------------------------------------------------- #
# fallback_title
# --------------------------------------------------------------------------- #


def test_fallback_title_prefers_user_message():
    assert fallback_title("用户第一条消息", "助手回复") == "用户第一条消息"


def test_fallback_title_truncates_long_messages():
    long_msg = "a" * 100
    result = fallback_title(long_msg, "")
    assert len(result) <= 21  # 20 + "…"
    assert result.endswith("…")


def test_fallback_title_falls_through_to_assistant():
    assert fallback_title("", "助手回复内容") == "助手回复内容"


def test_fallback_title_returns_default_when_all_empty():
    assert fallback_title("", "") == DEFAULT_TITLE
    assert fallback_title(None, None) == DEFAULT_TITLE


# --------------------------------------------------------------------------- #
# needs_title
# --------------------------------------------------------------------------- #


def test_needs_title_dict_compatibility():
    """needs_title 兼容 dict 输入（SQLite 行返回 dict）。"""
    assert needs_title({"title": DEFAULT_TITLE, "title_attempts": 0})
    assert needs_title({"title": DEFAULT_TITLE, "title_attempts": 2})
    assert not needs_title({"title": "Python 异步编程讨论", "title_attempts": 1})
    assert not needs_title({"title": DEFAULT_TITLE, "title_attempts": 3})  # 达上限
    assert not needs_title({"title": None, "title_attempts": 3})


def test_needs_title_session_object_compatibility():
    """needs_title 兼容类属性访问（Session dataclass）。"""

    class FakeSession:
        def __init__(self, title: str, attempts: int):
            self.title = title
            self.title_attempts = attempts

    assert needs_title(FakeSession(DEFAULT_TITLE, 0))
    assert not needs_title(FakeSession("Python 异步编程讨论", 1))
    assert not needs_title(FakeSession(DEFAULT_TITLE, 3))


# --------------------------------------------------------------------------- #
# MemoryStorageAdapter title_attempts 支持（hex 路径缺口补全）
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio()
async def test_memory_storage_tracks_title_attempts():
    """MemoryStorageAdapter 正确持久化 title_attempts。"""
    storage = MemoryStorageAdapter()
    sid = await storage.create_session()

    session = await storage.get_session(sid)
    assert session is not None
    assert session["title_attempts"] == 0

    await storage.update_session(sid, title="新标题", title_attempts=1)
    session = await storage.get_session(sid)
    assert session["title"] == "新标题"
    assert session["title_attempts"] == 1

    await storage.update_session(sid, title_attempts=2)
    session = await storage.get_session(sid)
    assert session["title"] == "新标题"  # 未变
    assert session["title_attempts"] == 2


# --------------------------------------------------------------------------- #
# TitleBackfill 集成（真实 SQLite + SessionRepository/MessageRepository）
# --------------------------------------------------------------------------- #


def _seed_session_with_messages(
    sid: str, user_text: str, assistant_text: str, *, title: str = DEFAULT_TITLE
) -> None:
    """在已创建的会话中写入 1 user + 1 assistant 消息，并把 message_count 置 2。

    TitleBackfill 依赖 ``list_untitled`` 的 ``message_count > 0`` 过滤，
    所以必须手动 bump ``message_count``。
    """
    session_repo = SessionRepository()
    message_repo = MessageRepository()
    now_ms = int(time.time() * 1000)
    message_repo.save(
        RepoMessage(
            id=str(uuid.uuid4()),
            session_id=sid,
            role="user",
            content=user_text,
            created_at=now_ms,
        )
    )
    message_repo.save(
        RepoMessage(
            id=str(uuid.uuid4()),
            session_id=sid,
            role="assistant",
            content=assistant_text,
            created_at=now_ms + 1,
        )
    )
    session_repo.update(sid, title=title, message_count=2)


@pytest.mark.asyncio()
async def test_backfill_processes_untitled_sessions():
    """TitleBackfill 扫描并补生成多个历史未命名会话。"""
    session_repo = SessionRepository()
    message_repo = MessageRepository()

    sids = [session_repo.create().id for _ in range(3)]
    for sid in sids:
        _seed_session_with_messages(
            sid,
            user_text="帮我解释 Python 的 GIL 是什么",
            assistant_text="GIL（全局解释器锁）是 CPython 中的一个互斥锁…",
        )

    backfill = TitleBackfill(
        session_repo,
        message_repo,
        generator_factory=lambda: _StableTitleLLM("Python GIL 详解"),
        startup_delay_s=0.0,
        min_interval_s=0.0,  # 测试不走速率闸门
        per_session_timeout_s=5.0,
    )
    stats = await backfill.run()

    assert stats["scanned"] == 3
    assert stats["titled"] == 3
    assert stats["failed"] == 0

    for sid in sids:
        updated = session_repo.get(sid)
        assert updated is not None
        assert updated.title == "Python GIL 详解"
        assert updated.title_attempts == 1


@pytest.mark.asyncio()
async def test_backfill_skips_already_attempted_sessions():
    """已达 attempts 上限的会话不被 list_untitled 命中。"""
    session_repo = SessionRepository()
    message_repo = MessageRepository()

    sid = session_repo.create().id
    _seed_session_with_messages(
        sid,
        user_text="用户消息",
        assistant_text="助手回复内容",
        title=DEFAULT_TITLE,
    )
    # 直接推到上限
    session_repo.update(sid, title_attempts=3)

    backfill = TitleBackfill(
        session_repo,
        message_repo,
        generator_factory=lambda: _StableTitleLLM("不应被使用"),
        startup_delay_s=0.0,
        min_interval_s=0.0,
        per_session_timeout_s=5.0,
    )
    stats = await backfill.run()

    # list_untitled 过滤了 attempts >= 3 的会话 → scanned=0
    assert stats["scanned"] == 0

    # 原会话状态不变
    unchanged = session_repo.get(sid)
    assert unchanged.title_attempts == 3


@pytest.mark.asyncio()
async def test_backfill_uses_heuristic_when_generator_factory_returns_none():
    """generator_factory 返回 None → 全部走启发式，仍然产生非空标题。"""
    session_repo = SessionRepository()
    message_repo = MessageRepository()

    sid = session_repo.create().id
    _seed_session_with_messages(
        sid,
        user_text="如何在 FastAPI 中实现依赖注入",
        assistant_text="使用 Depends() 注解即可实现依赖注入…",
    )

    backfill = TitleBackfill(
        session_repo,
        message_repo,
        generator_factory=lambda: None,  # 无 LLM
        startup_delay_s=0.0,
        min_interval_s=0.0,
        per_session_timeout_s=5.0,
    )
    stats = await backfill.run()

    assert stats["scanned"] == 1
    updated = session_repo.get(sid)
    # 启发式：取用户消息首行
    assert updated.title == "如何在 FastAPI 中实现依赖注入"
    assert updated.title_attempts == 1


# --------------------------------------------------------------------------- #
# Legacy /api/v1/chat/stream 事件链路（title_updated + title_pending + 落库）
# --------------------------------------------------------------------------- #


CHAT_STREAM_PATH = "/api/v1/chat/stream"


def _ensure_stream_registry() -> None:
    from backend.api.chat_stream_registry import StreamRegistry

    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()


def _parse_ndjson(text: str) -> List[dict]:
    return [json.loads(line) for line in text.split("\n") if line.strip()]


@pytest.mark.asyncio()
async def test_legacy_stream_emits_title_updated_event_and_persists_title():
    """legacy 路径：首轮对话后 DONE 事件带 title_pending，NDJSON 流里出现
    ``session_updated / title_updated`` 事件，DB 同步写入 title + attempts=1。
    """
    _ensure_stream_registry()
    session_repo = SessionRepository()
    # 默认 title="新对话" → needs_title(sess) 为真
    session = session_repo.create()
    sid = session.id

    # 用户消息 + 助手回复合并 ≥ MIN_CONTENT_FOR_LLM=20
    user_text = "帮我详细解释一下 Python 的 asyncio 事件循环工作原理"
    assistant_text = "asyncio 事件循环是 Python 异步 I/O 的核心调度器…"

    async def mock_run_loop(messages: Any, max_iterations: int = 5, **kwargs: Any) -> Any:
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(state=AgentState.DONE, iteration=0, content=assistant_text)

    # MockLLMAdapter 响应必须通过 _clean_title（2..30 字符，非 DEFAULT_TITLE）
    title_llm = MockLLMAdapter(
        responses=[CoreMessage(role=Role.ASSISTANT, content="asyncio 事件循环详解")]
    )

    from backend.core.legacy.agent_state import AgentEvent, AgentState

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent, patch(
        "backend.api.legacy_routes.TitleModelFactory"
    ) as MockFactory:
        MockAgent.return_value.run_loop = mock_run_loop
        MockFactory.build.return_value = title_llm

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Sage-Local-Authorization": "Bearer test-local-auth-token"},
        ) as ac:
            create_resp = await ac.post(
                CHAT_STREAM_PATH,
                json={"session_id": sid, "message": user_text},
            )
            assert create_resp.status_code == 200
            stream_id = create_resp.json()["streamId"]

            attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
            assert attach_resp.status_code == 200

    events = _parse_ndjson(attach_resp.text)
    event_types = [
        (e.get("type"), e.get("subtype"), e.get("state")) for e in events
    ]

    # 1) 必须出现 DONE 事件且带 title_pending=True
    done_events = [e for e in events if e.get("state") == "done" or e.get("type") == "done"]
    assert done_events, f"未找到 DONE 事件，events={event_types}"
    assert done_events[-1].get("title_pending") is True, (
        f"DONE 事件未带 title_pending=True: {done_events[-1]}"
    )

    # 2) 必须出现 session_updated / title_updated 事件，且 title 非 DEFAULT_TITLE
    title_events = [
        e
        for e in events
        if e.get("type") == "session_updated" and e.get("subtype") == "title_updated"
    ]
    assert title_events, f"未找到 title_updated 事件，events={event_types}"
    assert title_events[0]["session_id"] == sid
    assert title_events[0]["title"] == "asyncio 事件循环详解"

    # 3) DB 中会话 title / title_attempts 已更新
    updated = session_repo.get(sid)
    assert updated is not None
    assert updated.title == "asyncio 事件循环详解"
    assert updated.title_attempts == 1
