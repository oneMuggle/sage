"""Request-scoped tool execution context.

A ``ToolExecutionContext`` carries per-request data that the tool system
needs to make scope decisions -- most notably, the chat session id and
the set of Office documents the producer is allowed to attach to the LLM
context. It travels through the call stack via a ``ContextVar`` so that:

* the agent loop can pull the active context with ``current_tool_context()``
  without threading it through every helper signature, and
* concurrent ``asyncio`` tasks each see their own context (the ContextVar
  is per-task, not shared).

Public surface:

    ToolExecutionContext         # frozen dataclass
    set_tool_context(ctx)        # bind for the current task, returns token
    current_tool_context()       # read the active context (None if unset)
    reset_tool_context(token)    # restore previous binding (pair with set)

    set_approved_paths(paths)       # record paths approved for the current call
    current_approved_paths()        # read the approved-paths scope
    reset_approved_paths(token)     # restore (pair with set)

Why a frozen dataclass with a ``frozenset`` of doc ids:

* frozen -> callers can't mutate the scope after authorization, which
  would silently widen which docs the producer is allowed to load.
* ``frozenset`` -> hashable and immutable, suitable for use as a set
  member or as part of an LRU key.

Approved-paths scope (separate ContextVar, same lifetime):

* 当用户批准一次工作区外写入时，审批的绝对路径被写入此作用域；
  ``BaseTool._enforce_workspace`` 据此放行。作用域随当前工具调用结束
  reset（agent 在 ``_await_tool_execution`` 外层 try/finally 管理 token）。
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import FrozenSet, Optional


@dataclass(frozen=True)
class ToolExecutionContext:
    """Per-request tool execution context.

    Attributes:
        session_id: Chat session the context is bound to. Used by tools
            that need to look up session-scoped state (memory, profile,
            bindings).
        stream_id: Stream id the producer is currently generating for.
            Tools that emit side effects tied to a stream should record
            this so a stream replay can be correlated.
        binding_generation: Active session-workspace binding generation
            at authorization time. Lets downstream code detect rebinds
            and refuse stale attachments.
        office_doc_scope: Set of Office doc ids the producer is allowed
            to load into the LLM context. Empty frozenset means "no
            Office docs authorized" (not "all docs" -- callers must
            intersect with the active binding to widen).
    """

    session_id: str
    stream_id: str
    binding_generation: int
    office_doc_scope: FrozenSet[str]


#: The active ``ToolExecutionContext`` for the current asyncio task or
#: thread. Defaults to ``None`` so callers without an explicit request
#: see no context (e.g. unit tests, internal background jobs).
_tool_context_var: ContextVar[Optional[ToolExecutionContext]] = ContextVar(
    "backend_tool_execution_context", default=None
)


def set_tool_context(ctx: ToolExecutionContext) -> Token:
    """Bind ``ctx`` as the active context for the current task.

    Returns:
        A ``Token`` that must be passed back to :func:`reset_tool_context`
        once the surrounding work is done (typically from a ``finally``
        block). The token is opaque to callers; just pass it through.
    """
    return _tool_context_var.set(ctx)


def current_tool_context() -> Optional[ToolExecutionContext]:
    """Return the active context for the current task, or ``None`` if unset."""
    return _tool_context_var.get()


def reset_tool_context(token: Token) -> None:
    """Restore the binding captured by ``token``.

    Pairs with :func:`set_tool_context`. Callers should always invoke
    this in a ``finally`` so a later request never inherits a previous
    request's context.
    """
    _tool_context_var.reset(token)


#: The set of absolute paths approved by the user for the current tool
#: call (typically because the permission engine's path boundary
#: validator upgraded the write to ``needs_approval``). ``BaseTool._enforce_workspace``
#: consults this scope before rejecting a path as outside the workspace.
#: Defaults to the empty tuple so unapproved calls never inherit a prior
#: call's scope.
_approved_paths_var: ContextVar[tuple] = ContextVar(
    "backend_tool_approved_paths", default=()
)


def set_approved_paths(paths: tuple) -> Token:
    """Bind ``paths`` as the approved scope for the current task.

    ``paths`` is typically the tuple of absolute paths extracted from
    the tool call's arguments that triggered the approval flow. The
    caller must pass the token back to :func:`reset_approved_paths`
    (typically in a ``finally`` block) to prevent the scope from leaking
    into subsequent calls.
    """
    return _approved_paths_var.set(tuple(paths))


def current_approved_paths() -> tuple:
    """Return the approved-paths scope for the current task, or ``()`` if unset."""
    return _approved_paths_var.get()


def reset_approved_paths(token: Token) -> None:
    """Restore the binding captured by ``token``.

    Pairs with :func:`set_approved_paths`. Always invoke from a
    ``finally`` block.
    """
    _approved_paths_var.reset(token)


__all__ = [
    "ToolExecutionContext",
    "set_tool_context",
    "current_tool_context",
    "reset_tool_context",
    "set_approved_paths",
    "current_approved_paths",
    "reset_approved_paths",
]
