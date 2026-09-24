# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""LLM 流事件录制 / 回放（DSH 对标 R8，B3）。

对标 deepseek-harness 的 ``llm-replay``：录制/回放挂在流的唯一拦截点。
sage 的拦截点是 ``LLMClient.chat_stream_events``（env 三态，见该方法的
docstring）；本模块提供 tee 录制与按序回放两个纯 I/O 生成器。

录制格式：目录内 ``rec_NNNN.jsonl``（NNNN 递增），每行一个事件：

- ``{"kind": "content_delta", "text": str}``
- ``{"kind": "reasoning_delta", "text": str}``
- ``{"kind": "response", "response": {LLMResponse asdict}}``
- ``{"kind": "error", "message": str}``（录制中途异常——回放时重现为
  同位置抛错，保证失败路径也可测）

回放语义：按文件名排序逐文件重放；目录无录制文件时抛 :class:`LLMError`
（回放耗尽 = 测试/离线会话配置错误，绝不静默编造内容）。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from typing import Any, AsyncGenerator, List, Tuple

from backend.core.errors import LLMError, LLMErrorType
from backend.core.legacy.llm_client import LLMResponse

logger = logging.getLogger(__name__)


def _recording_paths(directory: str) -> List[str]:
    if not os.path.isdir(directory):
        return []
    names = sorted(n for n in os.listdir(directory) if n.startswith("rec_") and n.endswith(".jsonl"))
    return [os.path.join(directory, n) for n in names]


def _response_to_dict(response: LLMResponse) -> dict:
    data = asdict(response)
    return json.loads(json.dumps(data, ensure_ascii=False, default=str))


def _response_from_dict(data) -> LLMResponse:
    from backend.core.legacy.llm_client import LLMToolCall

    tool_calls = [LLMToolCall(**tc) for tc in (data.get("tool_calls") or [])]
    return LLMResponse(
        content=data.get("content") or "",
        reasoning_content=data.get("reasoning_content"),
        model=data.get("model") or "",
        finish_reason=data.get("finish_reason"),
        tool_calls=tool_calls,
        input_tokens=int(data.get("input_tokens") or 0),
        output_tokens=int(data.get("output_tokens") or 0),
        total_tokens=int(data.get("total_tokens") or 0),
        usage=data.get("usage"),
        raw=data.get("raw"),
    )


async def record_stream_events(
    directory: str,
    source: AsyncGenerator[Tuple[str, Any], None],
) -> AsyncGenerator[Tuple[str, Any], None]:
    """tee ``source`` 事件流到录制文件（原事件原样向下游透传）。"""
    os.makedirs(directory, exist_ok=True)
    index = len(_recording_paths(directory))
    path = os.path.join(directory, f"rec_{index:04d}.jsonl")
    # noqa 语境: 句柄须跨 async yield 存活，with 会在首个挂起点关闭文件
    fh = open(path, "w", encoding="utf-8")  # noqa: SIM115 — 手动生命周期（见上）
    try:
        async for kind, payload in source:
            if kind == "content_delta":
                line = {"kind": "content_delta", "text": payload}
            elif kind == "reasoning_delta":
                line = {"kind": "reasoning_delta", "text": payload}
            elif kind == "response":
                line = {"kind": "response", "response": _response_to_dict(payload)}
            else:
                # 未知事件类型：透传但记录占位（保证重放顺序可审计）
                line = {"kind": str(kind), "raw": str(payload)}
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
            fh.flush()
            yield kind, payload
    except Exception as exc:
        fh.write(json.dumps({"kind": "error", "message": str(exc)}, ensure_ascii=False) + "\n")
        fh.flush()
        raise
    finally:
        fh.close()
    logger.info("LLM 流已录制: %s", path)


async def replay_stream_events(
    directory: str,
) -> AsyncGenerator[Tuple[str, Any], None]:
    """按序重放录制目录中的事件流（不联网）。

    遇到 ``error`` 行在原位置抛 :class:`LLMError`（重现失败路径）。
    """
    paths = _recording_paths(directory)
    if not paths:
        raise LLMError(
            LLMErrorType.PARSING, f"回放目录无录制文件: {directory}"
        )
    for path in paths:
        logger.info("LLM 流回放: %s", path)
        with open(path, encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                event = json.loads(line)
                kind = event.get("kind")
                if kind == "content_delta":
                    yield "content_delta", event.get("text") or ""
                elif kind == "reasoning_delta":
                    yield "reasoning_delta", event.get("text") or ""
                elif kind == "response":
                    yield "response", _response_from_dict(event.get("response") or {})
                elif kind == "error":
                    raise LLMError(
                        LLMErrorType.SERVER_ERROR,
                        f"[replay] 录制的失败路径重放: {event.get('message')}",
                    )
                else:
                    logger.warning("回放跳过未知事件类型: %s", kind)


__all__ = ["record_stream_events", "replay_stream_events"]
