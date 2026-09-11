"""httpx 响应流的 byte-level tee。

设计要点:
- aiter_raw() 给的是 chunk 序列(httpx 内部按传输 chunk 切),我们逐 chunk 复制
- 回调抛异常立即向上传播(不吞),保证调用方知道下游异常
- 返回完整 bytes 便于调用方传给后续 streaming response 透传
"""
from __future__ import annotations

from typing import Callable, Union

# aiter_raw 在 httpx 0.23+ 返回 AsyncIterator[bytes],旧版本可能返回 AsyncByteStream
# 我们只依赖 aiter_raw,具体类型不强约束
_StreamLike = Union[object, "httpx.Response"]  # type: ignore[name-defined]  # noqa: F821
_OnChunk = Callable[[bytes], None]


async def tee_stream(
    upstream: _StreamLike,
    on_chunk: _OnChunk,
) -> bytes:
    """读 upstream.aiter_raw() 到底,逐 chunk 调 on_chunk,返回完整 bytes。

    Args:
        upstream: 有 aiter_raw() 方法的对象(httpx.Response 或测试 fake)
        on_chunk: 同步回调,接收每 chunk bytes;异常透传

    Returns:
        拼接后的所有 chunks(bytes)
    """
    pieces = []
    async for chunk in upstream.aiter_raw():
        on_chunk(chunk)  # 同步回调,异常直接向上抛
        pieces.append(chunk)
    return b"".join(pieces)
