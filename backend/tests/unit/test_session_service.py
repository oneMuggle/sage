"""SessionService 单元测试 (PG-A1, hex 迁移第一刀)。

RED 阶段:仅断言 SessionService 行为契约,实现尚未存在。所有 23 个
assertion 期望本文件落盘后立即失败 (ModuleNotFoundError 或
AssertionError),证明 TDD 起点正确。

依赖注入:遵循 ChatService 的"真实 adapter 优先"模式 ——
``MemoryStorageAdapter`` 走真实路径覆盖 storage 行为,仅
metrics / events 用简单 mock 验证 emit 契约。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
from backend.application.services.session_service import SessionService
from backend.domain import SessionNotFoundError

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def storage() -> MemoryStorageAdapter:
    """真实内存存储,覆盖 get/list/create/update/delete 全路径。"""
    return MemoryStorageAdapter()


@pytest.fixture()
def metrics() -> MagicMock:
    """只验证 metrics.gauge() 被调用,内容是实现细节。"""
    return MagicMock(spec=NoopMetricAdapter)


@pytest.fixture()
def events() -> MagicMock:
    """验证 emit(name, payload) 契约。"""
    return MagicMock()


@pytest.fixture()
def svc(storage, metrics, events) -> SessionService:
    return SessionService(storage=storage, metrics=metrics, events=events)


# --------------------------------------------------------------------------- #
# create_session
# --------------------------------------------------------------------------- #


class TestCreateSession:
    async def test_returns_storage_session_id(self, svc, storage):
        """create_session 委托给 storage, 返 storage 给的 ID。"""
        sid = await svc.create_session(title="hi")
        # 内存 adapter 返的 ID 形如 "mem-sess-N"
        assert isinstance(sid, str)
        assert sid.startswith("mem-")
        # 真持久化了
        assert (await storage.get_session(sid))["title"] == "hi"

    async def test_emits_session_created_with_id_and_title(self, svc, events):
        await svc.create_session(title="hello")
        name, payload = events.emit.call_args[0]
        assert name == "session_created"
        assert payload["title"] == "hello"
        assert isinstance(payload["session_id"], str)

    async def test_active_sessions_gauge_starts_at_one(self, svc, metrics):
        await svc.create_session()
        # gauge 至少被调一次,末次值应为 1.0
        last_call = metrics.gauge.call_args_list[-1]
        name, value = last_call[0][0], last_call[0][1]
        assert name.endswith("active_sessions")
        assert value == 1.0


# --------------------------------------------------------------------------- #
# list_sessions
# --------------------------------------------------------------------------- #


class TestListSessions:
    async def test_returns_storage_list(self, svc):
        sid = await svc.create_session(title="t1")
        result = await svc.list_sessions(limit=10, offset=0)
        assert isinstance(result, list)
        assert any(s["id"] == sid for s in result)

    async def test_pagination_slices_in_memory(self, svc):
        for _ in range(5):
            await svc.create_session(title="t")
        result = await svc.list_sessions(limit=2, offset=1)
        assert len(result) == 2


# --------------------------------------------------------------------------- #
# get_session
# --------------------------------------------------------------------------- #


class TestGetSession:
    async def test_returns_storage_dict(self, svc):
        sid = await svc.create_session(title="hi")
        result = await svc.get_session(sid)
        assert result is not None
        assert result["id"] == sid
        assert result["title"] == "hi"

    async def test_returns_none_when_missing(self, svc):
        assert await svc.get_session("ghost-id") is None


# --------------------------------------------------------------------------- #
# update_session
# --------------------------------------------------------------------------- #


class TestUpdateSession:
    async def test_title_only_passes_to_storage(self, svc, storage):
        sid = await svc.create_session(title="old")
        result = await svc.update_session(sid, title="new", is_pinned=None)
        assert result["title"] == "new"
        # 真正落库
        assert (await storage.get_session(sid))["title"] == "new"

    async def test_raises_session_not_found(self, svc):
        with pytest.raises(SessionNotFoundError):
            await svc.update_session("ghost", title="x")

    async def test_no_fields_no_storage_update_returns_current(self, svc):
        sid = await svc.create_session(title="t")
        result = await svc.update_session(sid)
        assert result["id"] == sid
        assert result["title"] == "t"


# --------------------------------------------------------------------------- #
# delete_session
# --------------------------------------------------------------------------- #


class TestDeleteSession:
    async def test_existing_returns_true(self, svc):
        sid = await svc.create_session(title="doomed")
        ok = await svc.delete_session(sid)
        assert ok is True
        # 再 get 应 None
        assert await svc.get_session(sid) is None

    async def test_missing_returns_false(self, svc):
        ok = await svc.delete_session("never-existed")
        assert ok is False

    async def test_active_sessions_counter_does_not_go_negative(self, svc):
        # counter 从 0 开始,删一个不存在的会话不应减到 -1
        await svc.delete_session("ghost")
        # 检查内部计数器
        assert svc._active_session_count == 0


# --------------------------------------------------------------------------- #
# list_messages
# --------------------------------------------------------------------------- #


class TestListMessages:
    async def test_empty_session_returns_empty_list(self, svc):
        sid = await svc.create_session(title="empty")
        result = await svc.list_messages(sid, limit=20, offset=0)
        assert result == []

    async def test_returns_persisted_messages(self, svc, storage):
        sid = await svc.create_session(title="chat")
        from backend.domain.message import Message, Role

        await storage.append_message(sid, Message(role=Role.USER, content="hi"))
        await storage.append_message(sid, Message(role=Role.ASSISTANT, content="hello"))
        result = await svc.list_messages(sid, limit=20, offset=0)
        assert len(result) == 2
        assert result[0]["content"] == "hi"
        assert result[1]["content"] == "hello"
