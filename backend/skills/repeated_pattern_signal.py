"""Repeated pattern signal — wire PatternDetector into the ReviewQueue.

Implements the "repeated pattern mining" trigger type for the background review
system: when the same tool signature (tool_name + sorted parameter keys) appears
``>= threshold`` times in a session, enqueue a ``repeated_pattern`` review event
so the LLM-driven ReviewService can draft a reusable skill from the user's flow.

Design follows ``SkillUsageStore._check_low_success_rate`` (best-effort, sync
``enqueue()``, outer try/except, ``logger.debug`` on skip).  Exceptions never
propagate — repeated pattern detection is an enhancement and must not break the
chat hot path.

Example:
    >>> detect_and_enqueue("s1", [response1, response2, response3])
    "read:path"  # pattern signature detected
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, List, Optional

logger = logging.getLogger(__name__)

# 默认触发阈值（与 PatternDetector 默认一致）
DEFAULT_REPEATED_PATTERN_THRESHOLD = 3

# 写入 context 时保留的 sample_calls 上限（避免 prompt 过大）
_MAX_SAMPLE_CALLS = 5


def _serialize_tool_calls(messages: Iterable[Any]) -> List[dict]:
    """从一组 Message 中提取所有 tool_calls，统一序列化为 ``{tool, args}``。

    复用 ``chat_service`` 已有的 ``tool_calls_serialized`` 形态
    （``chat_service.py:462``），便于 PatternDetector 直接消费。

    Message 缺失 ``tool_calls`` / ``tool_calls`` 不是列表 / 单个元素不是
    ToolCall 状对象 —— 全部静默跳过，best-effort 契约。
    """
    serialized: List[dict] = []
    for msg in messages:
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            continue
        for tc in tool_calls:
            name = getattr(tc, "name", None)
            if not isinstance(name, str) or not name:
                continue
            args = getattr(tc, "args", None)
            serialized.append({"tool": name, "args": args if isinstance(args, dict) else {}})
    return serialized


def detect_and_enqueue(
    session_id: str,
    history_messages: Iterable[Any],
    *,
    threshold: int = DEFAULT_REPEATED_PATTERN_THRESHOLD,
    span: Any = None,
) -> Optional[str]:
    """在 chat turn 结束时检测重复工具模式，命中则入队 review_queue。

    Args:
        session_id: 当前会话 ID。
        history_messages: 已加载的 history + 当前 assistant response
            （必须包含本轮新产生的 tool_calls）。
        threshold: 同一 signature 出现次数达到该阈值才触发。默认 3。
        span: 可选 OpenTelemetry span，用于打 ``review.repeated_pattern.*`` 属性。

    Returns:
        触发的 signature 字符串（如 ``"read:path"``）；未触发或异常时返回 ``None``。

    行为约束（best-effort）：
        - 任何异常仅 ``logger.debug`` 记录，绝不外抛
        - 不阻塞 chat 主路径
        - 序列化和检测均同步执行（参考 ``_check_low_success_rate``）
    """
    try:
        tool_calls = _serialize_tool_calls(history_messages)
        if len(tool_calls) < threshold:
            return None

        from backend.skills.pattern_detector import PatternDetector

        pattern = PatternDetector().detect_repeated_pattern(
            tool_calls, threshold=threshold
        )
        if pattern is None:
            return None

        signature = pattern["signature"]
        count = pattern["count"]
        sample_calls = pattern["tool_calls"][:_MAX_SAMPLE_CALLS]

        from backend.skills.review_queue import get_review_queue

        review_queue = get_review_queue()
        review_queue.enqueue(
            trigger_type="repeated_pattern",
            session_id=session_id,
            context={
                "signature": signature,
                "count": count,
                "sample_calls": sample_calls,
                "threshold": threshold,
            },
        )
        logger.info(
            "Enqueued repeated_pattern review (session=%s, signature=%s, count=%d)",
            session_id,
            signature,
            count,
        )
        if span is not None:
            try:
                span.set_attribute("review.repeated_pattern_enqueued", True)
                span.set_attribute("review.repeated_pattern_signature", signature)
                span.set_attribute("review.repeated_pattern_count", count)
            except Exception:  # noqa: BLE001 - span 装饰不影响主流程
                pass
        return signature
    except Exception as exc:  # noqa: BLE001 - 整段检测是 best-effort
        logger.debug(f"Repeated pattern detection skipped: {exc}")
        return None
