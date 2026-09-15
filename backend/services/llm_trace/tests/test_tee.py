"""Tests for tee_stream httpx aiter_raw helper.

覆盖:
- 完整 chunk 序列: 返回拼接 bytes + 回调收到每 chunk
- 空 stream: 返回 b"" + 回调零次调用
- 回调抛异常: 异常透传到调用方(不吞)
- 二进制内容: 不在 tee 层强行解码
"""
from __future__ import annotations

import pytest

from backend.services.llm_trace.tee import tee_stream


class _FakeChunkedResponse:
    """模拟 httpx.Response 的 aiter_raw 行为,无网络。"""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self._idx = 0

    async def aiter_raw(self):
        for c in self._chunks:
            yield c

    async def aread(self):  # pragma: no cover - 不应被调用
        raise AssertionError("tee_stream should not call aread()")


@pytest.mark.asyncio()
async def test_tee_returns_concatenated_bytes_and_invokes_callback():
    chunks = [b"hello ", b"world", b"!"]
    resp = _FakeChunkedResponse(chunks)
    captured = []

    result = await tee_stream(resp, lambda b: captured.append(b))

    assert result == b"hello world!"
    assert captured == chunks  # 回调收到每个原始 chunk


@pytest.mark.asyncio()
async def test_tee_handles_empty_stream():
    resp = _FakeChunkedResponse([])
    captured = []

    result = await tee_stream(resp, lambda b: captured.append(b))

    assert result == b""
    assert captured == []


@pytest.mark.asyncio()
async def test_tee_propagates_callback_exceptions():
    resp = _FakeChunkedResponse([b"a", b"b"])

    def bad_cb(b):
        raise RuntimeError("callback boom")

    with pytest.raises(RuntimeError, match="callback boom"):
        await tee_stream(resp, bad_cb)


@pytest.mark.asyncio()
async def test_tee_handles_binary_content():
    """非 UTF-8 内容不应在 tee 层被强行解码。"""
    chunks = [b"\x00\x01", b"\xff\xfe\xfd"]
    resp = _FakeChunkedResponse(chunks)

    result = await tee_stream(resp, lambda _b: None)

    assert result == b"\x00\x01\xff\xfe\xfd"
