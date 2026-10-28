"""R159 — MemoryPort 记忆端口协议单元测试。

覆盖：协议三方法（retrieve/store/compress）声明、duck-type 实现满足、
方法签名兼容（缺省参数）、异步方法返回协程。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.domain.memory import MemoryContext
from backend.ports.memory import MemoryPort

pytestmark = pytest.mark.unit


class _FakeMemoryPort:
    """MemoryPort 的最小 duck-type 实现。"""

    async def retrieve(self, query, session_id, limit=5):
        return MemoryContext()

    async def store(self, content, session_id, importance=5, tags=None):
        return "id-1"

    async def compress(self, session_id):
        return None


def test_memory_port_protocol_declares_methods():
    for method in ("retrieve", "store", "compress"):
        assert callable(getattr(MemoryPort, method, None))


def test_duck_typed_implementation_satisfies_contract():
    impl = _FakeMemoryPort()
    for method in ("retrieve", "store", "compress"):
        assert callable(getattr(impl, method))


def test_all_methods_are_async():
    impl = _FakeMemoryPort()
    coro1 = impl.retrieve("q", "s1")
    coro2 = impl.store("c", "s1")
    coro3 = impl.compress("s1")
    for coro in (coro1, coro2, coro3):
        assert asyncio.iscoroutine(coro)

    async def _drain():
        for coro in (coro1, coro2, coro3):
            await coro

    asyncio.run(_drain())


@pytest.mark.asyncio()
async def test_retrieve_and_store_signature_defaults():
    class _RecordingPort:
        def __init__(self):
            self.calls = []

        async def retrieve(self, query, session_id, limit=5):
            self.calls.append(("retrieve", query, session_id, limit))
            return MemoryContext()

        async def store(self, content, session_id, importance=5, tags=None):
            self.calls.append(("store", content, session_id, importance, tags))
            return "new-id"

        async def compress(self, session_id):
            self.calls.append(("compress", session_id))

    port = _RecordingPort()
    ctx = await port.retrieve("火锅", "s1")
    assert isinstance(ctx, MemoryContext)
    assert ctx.has_memories is False

    mid = await port.store("内容", "s1", importance=7, tags=["t"])
    assert mid == "new-id"

    assert port.calls[0] == ("retrieve", "火锅", "s1", 5)
    assert port.calls[1] == ("store", "内容", "s1", 7, ["t"])
    await port.compress("s1")
    assert port.calls[2] == ("compress", "s1")
