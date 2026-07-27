"""ToolExecutionContext + ContextVar tests.

Covers:
- default ``current_tool_context()`` returns ``None``
- ``set_tool_context(ctx)`` returns a token; ``current_tool_context()`` returns ctx
- ``reset_tool_context(token)`` restores previous state (None -> None, ctx -> ctx)
- nested tokens stack correctly (outer -> inner -> reset to outer)
- ``reset_tool_context`` happens even when work raises (try/finally pattern)
- concurrent ``asyncio.gather`` with two distinct contexts gives each task its own
  context (the ContextVar is per-task, not shared)

These tests are written before the implementation lives in
``backend/tools/context.py`` -- they will FAIL until the module exposes the
``ToolExecutionContext`` dataclass, the ContextVar, and the three helpers.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.tools.context import (
    ToolExecutionContext,
    current_tool_context,
    reset_tool_context,
    set_tool_context,
)

pytestmark = pytest.mark.unit


def _ctx(
    session_id: str = "sess-1",
    stream_id: str = "stream-1",
    binding_generation: int = 1,
    office_doc_scope: frozenset = frozenset(),
) -> ToolExecutionContext:
    """Build a ToolExecutionContext with sensible defaults for tests."""
    return ToolExecutionContext(
        session_id=session_id,
        stream_id=stream_id,
        binding_generation=binding_generation,
        office_doc_scope=office_doc_scope,
    )


# ---------- default state ----------


def test_current_tool_context_default_is_none():
    """Outside any set_tool_context() block, current_tool_context() returns None."""
    assert current_tool_context() is None


# ---------- set / reset roundtrip ----------


def test_set_tool_context_makes_current_visible():
    """set_tool_context(ctx) makes current_tool_context() return ctx."""
    ctx = _ctx(session_id="alpha")
    token = set_tool_context(ctx)
    try:
        assert current_tool_context() is ctx
    finally:
        reset_tool_context(token)


def test_reset_tool_context_restores_none():
    """After reset, current_tool_context() is None again."""
    ctx = _ctx()
    token = set_tool_context(ctx)
    assert current_tool_context() is ctx
    reset_tool_context(token)
    assert current_tool_context() is None


# ---------- nested tokens ----------


def test_nested_tokens_stack_and_unwind():
    """Outer -> inner -> reset returns to outer, then reset returns to None."""
    outer = _ctx(session_id="outer")
    inner = _ctx(session_id="inner")

    outer_token = set_tool_context(outer)
    assert current_tool_context() is outer

    inner_token = set_tool_context(inner)
    assert current_tool_context() is inner

    # unwind inner first
    reset_tool_context(inner_token)
    assert current_tool_context() is outer

    # unwind outer last
    reset_tool_context(outer_token)
    assert current_tool_context() is None


# ---------- reset on exception ----------


def test_reset_on_exception_restores_previous():
    """A raise inside the with-style block is followed by reset -- current is None."""
    ctx = _ctx(session_id="boom")
    token = set_tool_context(ctx)
    assert current_tool_context() is ctx
    try:
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            pass
        # After the inner try/except, the context is still set -- reset is up
        # to the caller. Verify the manual reset pattern works.
        reset_tool_context(token)
    except Exception:
        # Defensive -- the inner try must have caught everything.
        pytest.fail("reset pattern raised unexpectedly")

    assert current_tool_context() is None


def test_no_leak_into_sibling_test_when_reset_is_explicit():
    """A new test observes a clean ``None`` regardless of earlier tests.

    Sanity check: explicit reset in test bodies is required by callers,
    so a new test should always observe a clean ``None`` regardless of
    any earlier test that forgot to reset. ContextVar tokens are
    per-asyncio-task, so on a fresh sync test the default is always None.
    """
    # No setup -- straight to assertions
    assert current_tool_context() is None


# ---------- concurrent asyncio.gather isolation ----------


@pytest.mark.asyncio()
async def test_concurrent_tasks_get_isolated_contexts():
    """Two concurrent asyncio tasks each see their own context, not each other's."""
    ctx_a = _ctx(session_id="task-a")
    ctx_b = _ctx(session_id="task-b")

    seen: dict = {}

    async def worker(name: str, ctx: ToolExecutionContext) -> None:
        token = set_tool_context(ctx)
        try:
            # Yield control so the other task interleaves.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            seen[name] = current_tool_context().session_id
        finally:
            reset_tool_context(token)
            current = current_tool_context()
            seen[f"{name}_after_reset"] = current.session_id if current is not None else None

    await asyncio.gather(worker("a", ctx_a), worker("b", ctx_b))

    assert seen["a"] == "task-a"
    assert seen["b"] == "task-b"
    # After reset, each task sees None again.
    assert seen["a_after_reset"] is None
    assert seen["b_after_reset"] is None


@pytest.mark.asyncio()
async def test_default_inside_task_is_none():
    """Inside a fresh task with no set_tool_context(), current is None."""
    assert current_tool_context() is None
    await asyncio.sleep(0)
    assert current_tool_context() is None


# ---------- dataclass immutability ----------


def test_tool_execution_context_is_frozen():
    """ToolExecutionContext is frozen -- mutation raises FrozenInstanceError."""
    from dataclasses import FrozenInstanceError

    ctx = _ctx(session_id="immutable")
    with pytest.raises(FrozenInstanceError):
        # dataclass(frozen=True) raises FrozenInstanceError (AttributeError subclass)
        ctx.session_id = "tampered"  # type: ignore[misc]


def test_tool_execution_context_equality():
    """Two contexts with the same fields compare equal (frozen dataclass __eq__)."""
    a = _ctx(session_id="x", binding_generation=3, office_doc_scope=frozenset({"d1"}))
    b = _ctx(session_id="x", binding_generation=3, office_doc_scope=frozenset({"d1"}))
    assert a == b


def test_office_doc_scope_is_frozenset_in_constructor():
    """office_doc_scope is stored as a frozenset; frozenset input is preserved."""
    ctx = _ctx(office_doc_scope=frozenset({"a", "b"}))
    assert isinstance(ctx.office_doc_scope, frozenset)
    assert ctx.office_doc_scope == frozenset({"a", "b"})
