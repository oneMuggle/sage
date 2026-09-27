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

__all__ = ["_check_request_within_window", "_resolve_effective_window"]


def _resolve_effective_window(  # noqa: PLR0911 — Task 5 priority cascade, each branch is a distinct user-facing mode
    model_id: Optional[str] = None,
    max_context: Optional[int] = None,
    request_endpoint_id: Optional[str] = None,
    auto_context: Optional[bool] = None,
) -> Optional[int]:
    """Task 5: Resolve effective context window from model catalog.

    Priority for ``endpoint_id``: request > persisted settings > None.
    Behaviour by ``auto_context`` flag (after catalog resolve):

    - ``auto_context=True``  → resolve from catalog; ``max_context``, if
      set, is applied as a safety upper bound (``min(catalog, max)``).
      This is the path that lets the UI's ``autoContext`` switch actually
      turn on catalog-driven window sizing.
    - ``auto_context=False`` → fixed cap at ``max_context`` (user pinned
      a value). Catalog caps still apply via effective_window.
    - ``auto_context=None``  → resolve from catalog (the default for
      callers that do not yet pass the field), 4096 default cap.

    Returns ``max_context`` if the catalog cannot be resolved, else
    ``None`` so callers can decide how to fall back.
    """
    try:
        from backend.data.database import get_database
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository
        from backend.model_catalog.context import effective_window
        from backend.model_catalog.repository import CatalogRepository
        from backend.model_catalog.schemas import EndpointKey

        raw = SettingsRepository().get_json("app_settings")
        if not isinstance(raw, dict):
            return max_context if max_context else None
        settings = to_camel(raw)
        endpoints = settings.get("endpoints") or []
        if not isinstance(endpoints, list):
            return max_context if max_context else None

        # Priority: request endpoint_id > persisted settings
        endpoint_id = None
        if request_endpoint_id:
            # Verify the request endpoint_id exists in the endpoints list
            ep = next(
                (e for e in endpoints if isinstance(e, dict) and e.get("id") == request_endpoint_id),
                None,
            )
            if ep is not None:
                endpoint_id = request_endpoint_id

        if not endpoint_id:
            # Fallback to persisted settings
            selections = settings.get("modelSelections") or {}
            chat_sel = selections.get("chatModel") if isinstance(selections, dict) else None
            if isinstance(chat_sel, dict) and chat_sel.get("endpointId"):
                ep_id = chat_sel["endpointId"]
                ep = next(
                    (e for e in endpoints if isinstance(e, dict) and e.get("id") == ep_id),
                    None,
                )
                if ep is not None:
                    endpoint_id = ep_id

        if not endpoint_id or not model_id:
            return max_context if max_context else None

        repo = CatalogRepository(get_database())
        resolved = repo.resolve(EndpointKey(endpoint_id=endpoint_id, model_id=model_id))
        # auto_context=True (UI toggle on): catalog-driven window with
        # max_context as a safety upper bound. This is the only branch
        # where the UI's autoContext switch actually reaches catalog
        # resolution — without it, the previous logic made max_context
        # always win and the toggle was inert.
        if auto_context is True:
            # effective_window(automatic=True) ignores ``fixed`` per the
            # schema contract, so the natural catalog window is returned
            # first and only then clamped to max_context. 4096 is a
            # stand-in positive int — its value is discarded.
            window = effective_window(
                resolved.limits, automatic=True, fixed=4096,
            )
            if max_context:
                window = min(window, max_context)
            return window
        # auto_context=False: user explicitly pinned a value, treat as cap.
        if auto_context is False and max_context:
            return effective_window(
                resolved.limits, automatic=False, fixed=max_context,
            )
        # auto_context=None (or False without max_context): resolve from
        # catalog, 4096 default ceiling.
        return effective_window(
            resolved.limits, automatic=True, fixed=4096,
        )
    except Exception:
        return max_context if max_context else None


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
