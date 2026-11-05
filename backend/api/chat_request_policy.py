# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""聊天请求窗口策略（C2b，DSH 对标 R26）。

``_resolve_effective_window`` / ``_check_request_within_window`` 此前在
legacy_routes 与四个 C1 路由组模块（memory / skills / memory_list /
skill_draft）中**五份逐字重复**——每次调整优先级级联都要同步五处，
漂移风险随份数线性增长。本模块收敛为唯一实现：

- ``_resolve_effective_window``：Task 5 目录驱动的上下文窗口解析
  （endpoint 优先级 + auto_context 三态 + fail-safe 回退）；
- ``_check_request_within_window``：请求超窗显式 400（历史已截断后，
  system / 附件 / 本轮输入单独超窗时的确定性拒绝）。

各路由模块 ``from backend.api.chat_request_policy import`` 同名函数，
FastAPI 注解解析与既有测试（含 ``from backend.api.legacy_routes import
_resolve_effective_window`` 的再导出路径）均不受影响。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from fastapi import HTTPException

from backend.chat.compaction import estimate_messages_tokens
from backend.services.context_window import (  # noqa: F401 —— 再导出供 legacy_routes / main.py 沿用旧路径
    _resolve_effective_window,
)

__all__ = ["_check_request_within_window", "_resolve_effective_window"]


def _check_request_within_window(
    messages: Sequence[Dict[str, Any]],
    effective_window: Optional[int],
) -> None:
    """Brief line 16: explicit reject when required content overshoots window.

    The history was already truncated to ``max(0, effective_window - reserve)``,
    so this guard only fires when system / attachments / trailing_system /
    current user input alone exceed the resolved window (e.g., a 1 MB
    attachment + a long system prompt against a 4K-window model). Without
    this check the producer would silently send an over-budget request that
    the upstream LLM truncates or errors on — this gives the caller a
    deterministic 400 instead.

    No-op when the catalog has not resolved a window (``effective_window``
    is None or non-positive) so callers without catalog data keep the legacy
    behaviour.
    """
    if effective_window is None or effective_window <= 0:
        return
    total = estimate_messages_tokens(messages)
    if total > effective_window:
        raise HTTPException(
            status_code=400,
            detail=(
                f"required content (system + history + attachments + current "
                f"input) ~{total} tokens exceeds resolved context window "
                f"({effective_window} tokens); reduce input length, drop "
                f"attachments, or pick a larger-context model"
            ),
        )
