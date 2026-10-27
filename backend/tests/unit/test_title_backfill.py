"""TitleBackfill — 单元测试

覆盖启动回补的查询、生成、落库与降级路径；不触真实 SQLite / LLM。
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

import pytest

from backend.chat.title_generator import DEFAULT_TITLE
from backend.domain.message import Message, Role
from backend.scheduler.title_backfill import TitleBackfill


class _FakeSession:
    def __init__(self, session_id: str, title: str = DEFAULT_TITLE, attempts: int = 0):
        self.id = session_id
        self.title = title
        self.title_attempts = attempts


class _FakeSessionRepo:
    def __init__(self, sessions: List[_FakeSession], fail_query: bool = False):
        self._sessions = sessions
        self._fail_query = fail_query
        self.updates: List[Dict[str, object]] = []
        self.last_limit: Optional[int] = None

    def list_untitled(self, placeholder_title, max_attempts, limit=100):
        if self._fail_query:
            raise RuntimeError("db down")
        self.last_limit = limit
        return list(self._sessions)[:limit]

    def update(self, session_id: str, **fields):
        self.updates.append({"session_id": session_id, **fields})
        return True


class _FakeMessageRepo:
    def __init__(self, by_session: Dict[str, List[Message]], fail: bool = False):
        self._by_session = by_session
        self._fail = fail

    def get_by_session(self, session_id: str, limit: int = 100):
        if self._fail:
            raise RuntimeError("read failed")
        return list(self._by_session.get(session_id, []))[:limit]


def _msgs(user: str = "", assistant: str = "") -> List[Message]:
    out = []
    if user:
        out.append(Message(role=Role.USER, content=user))
    if assistant:
        out.append(Message(role=Role.ASSISTANT, content=assistant))
    return out


def _make(
    sessions,
    by_session=None,
    *,
    factory=None,
    fail_query=False,
    fail_messages=False,
    **kwargs,
):
    repo = _FakeSessionRepo(sessions, fail_query=fail_query)
    messages = _FakeMessageRepo(by_session or {}, fail=fail_messages)
    kwargs.setdefault("min_interval_s", 0.0)
    kwargs.setdefault("per_session_timeout_s", 1.0)
    backfill = TitleBackfill(
        session_repo=repo,
        message_repo=messages,
        generator_factory=factory or (lambda: None),
        **kwargs,
    )
    return backfill, repo


# ---------------------------------------------------------------------------
# 正常路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_titles_untitled_session_with_heuristic():
    sessions = [_FakeSession("s1", attempts=0)]
    backfill, repo = _make(
        sessions, {"s1": _msgs("帮我写一个排序算法", "好的，下面是实现")}
    )

    stats = await backfill.run()

    assert stats == {"scanned": 1, "titled": 1, "failed": 0}
    assert repo.updates == [
        {"session_id": "s1", "title": "帮我写一个排序算法", "title_attempts": 1}
    ]


@pytest.mark.asyncio()
async def test_stats_aggregate_multiple_sessions():
    sessions = [_FakeSession("s1"), _FakeSession("s2", attempts=2)]
    backfill, repo = _make(
        sessions,
        {
            "s1": _msgs("第一个会话主题", "回复一"),
            "s2": _msgs("第二个会话主题", "回复二"),
        },
    )

    stats = await backfill.run()

    assert stats["scanned"] == 2
    assert stats["titled"] == 2
    assert len(repo.updates) == 2
    assert repo.updates[1]["title_attempts"] == 3


# ---------------------------------------------------------------------------
# 降级路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_empty_messages_records_attempt_without_title():
    sessions = [_FakeSession("s1")]
    backfill, repo = _make(sessions, {"s1": []})

    stats = await backfill.run()

    assert stats == {"scanned": 1, "titled": 0, "failed": 1}
    assert repo.updates[0]["title"] == DEFAULT_TITLE
    assert repo.updates[0]["title_attempts"] == 1


@pytest.mark.asyncio()
async def test_query_failure_returns_zero_stats():
    backfill, _ = _make([_FakeSession("s1")], fail_query=True)

    stats = await backfill.run()

    assert stats == {"scanned": 0, "titled": 0, "failed": 0}


@pytest.mark.asyncio()
async def test_message_read_failure_counts_as_failed():
    sessions = [_FakeSession("s1")]
    backfill, repo = _make(sessions, fail_messages=True)

    stats = await backfill.run()

    assert stats == {"scanned": 1, "titled": 0, "failed": 1}
    assert repo.updates[0]["title"] == DEFAULT_TITLE


@pytest.mark.asyncio()
async def test_generator_factory_failure_falls_back_to_heuristic():
    sessions = [_FakeSession("s1")]
    by_session = {"s1": _msgs("数据分析方案", "我来分析")}

    def boom():
        raise RuntimeError("no llm")

    backfill, repo = _make(sessions, by_session, factory=boom)

    stats = await backfill.run()

    assert stats["titled"] == 1
    assert repo.updates[0]["title"] == "数据分析方案"


@pytest.mark.asyncio()
async def test_generation_timeout_records_attempt(monkeypatch):
    import backend.scheduler.title_backfill as mod

    class _SlowGenerator:
        def __init__(self, llm):
            pass

        async def generate(self, user_message, assistant_message):
            await asyncio.sleep(5)
            return "never"

    monkeypatch.setattr(mod, "TitleGenerator", _SlowGenerator)
    sessions = [_FakeSession("s1")]
    backfill, repo = _make(
        sessions,
        {"s1": _msgs("这是一个足够长的用户消息", "回复")},
        per_session_timeout_s=0.01,
    )

    stats = await backfill.run()

    assert stats == {"scanned": 1, "titled": 0, "failed": 1}
    assert repo.updates[0]["title"] == DEFAULT_TITLE


@pytest.mark.asyncio()
async def test_update_failure_does_not_raise():
    class _BoomRepo(_FakeSessionRepo):
        def update(self, session_id, **fields):
            raise RuntimeError("write failed")

    repo = _BoomRepo([_FakeSession("s1")])
    messages = _FakeMessageRepo({"s1": _msgs("主题内容", "回复")})
    backfill = TitleBackfill(
        session_repo=repo,
        message_repo=messages,
        generator_factory=lambda: None,
        min_interval_s=0.0,
        per_session_timeout_s=1.0,
    )

    stats = await backfill.run()

    assert stats["scanned"] == 1
    assert stats["titled"] == 1  # 生成成功但落库失败——按生成结果计数


# ---------------------------------------------------------------------------
# 批量上限与调度
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_max_batch_forwarded_to_repo():
    sessions = [_FakeSession(f"s{i}") for i in range(5)]
    backfill, repo = _make(sessions, max_batch=2)

    stats = await backfill.run()

    assert repo.last_limit == 2
    assert stats["scanned"] == 2


@pytest.mark.asyncio()
async def test_schedule_then_stop_is_idempotent():
    backfill, _ = _make([_FakeSession("s1")], startup_delay_s=60)
    backfill.schedule()
    backfill.schedule()  # 第二次无副作用

    await backfill.stop()
    # 任务已取消且不抛出
    assert backfill._task is None


@pytest.mark.asyncio()
async def test_delayed_run_executes_after_delay():
    sessions = [_FakeSession("s1")]
    backfill, repo = _make(
        sessions, {"s1": _msgs("延迟后执行的主题", "回复")}, startup_delay_s=0.01
    )

    backfill.schedule()
    await asyncio.wait_for(backfill._task, timeout=2.0)

    assert repo.updates[0]["title"] == "延迟后执行的主题"
