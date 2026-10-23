# ruff: noqa: UP006, UP007, UP035, UP045
"""Fiber / PluginHost 单测：状态机、依赖驱动、级联卸载、副作用回收。"""

from __future__ import annotations

import asyncio
from typing import Any, List

import pytest

from backend.application.kernel.fiber import (
    FiberError,
    FiberStateError,
    PluginHost,
)
from backend.domain.plugin import FiberState


async def _settle(rounds: int = 3) -> None:
    """让服务变更触发的后台 task 跑完。"""
    for _ in range(rounds):
        await asyncio.sleep(0)


async def test_plugin_without_dependencies_starts() -> None:
    host = PluginHost()
    calls: List[str] = []
    fiber = host.load("plain", lambda _ctx: calls.append("plain"))
    await fiber.start()

    assert fiber.state is FiberState.ACTIVE
    assert calls == ["plain"]
    assert host.active_plugins() == ["plain"]


async def test_missing_dependency_keeps_pending_then_starts() -> None:
    host = PluginHost()
    calls: List[str] = []
    fiber = host.load("needs-tools", lambda _ctx: calls.append("apply"), inject=["tools"])

    await fiber.start()
    assert fiber.state is FiberState.PENDING
    assert calls == []

    host.services.provide("tools", object(), owner="core")
    await fiber.refresh()

    assert fiber.state is FiberState.ACTIVE
    assert calls == ["apply"]


async def test_apply_failure_is_recorded() -> None:
    host = PluginHost()

    def boom(_ctx: Any) -> None:
        raise RuntimeError("bad plugin")

    fiber = host.load("broken", boom)
    await fiber.start()

    assert fiber.state is FiberState.FAILED
    assert isinstance(fiber.error, RuntimeError)
    assert host.states() == {"broken": FiberState.FAILED}


async def test_dependency_removal_disposes_and_restores() -> None:
    host = PluginHost()
    release = host.services.provide("tools", object(), owner="core")
    calls: List[str] = []
    fiber = host.load("watcher", lambda _ctx: calls.append("apply"), inject=["tools"])

    await fiber.start()
    assert fiber.state is FiberState.ACTIVE

    release()  # 服务消失 → 自动卸载
    await _settle()
    assert fiber.state is FiberState.DISPOSED

    host.services.provide("tools", object(), owner="core")  # 服务恢复 → 自动重载
    await _settle()
    assert fiber.state is FiberState.ACTIVE
    assert calls == ["apply", "apply"]


async def test_effects_are_disposed_with_plugin() -> None:
    host = PluginHost()
    cleaned: List[str] = []

    def apply(ctx: Any) -> None:
        ctx.effect(lambda: (lambda: cleaned.append("resource")))

    fiber = host.load("with-effect", apply)
    await fiber.start()
    assert cleaned == []

    await fiber.dispose()
    assert cleaned == ["resource"]
    assert fiber.state is FiberState.DISPOSED


async def test_event_listeners_are_removed_on_dispose() -> None:
    host = PluginHost()
    seen: List[str] = []

    def apply(ctx: Any) -> None:
        ctx.on("tool/post", lambda *_: seen.append("hit"))

    fiber = host.load("listener", apply)
    await fiber.start()
    host.events.emit("tool/post")
    assert seen == ["hit"]

    await fiber.dispose()
    host.events.emit("tool/post")
    assert seen == ["hit"]
    assert host.events.handler_count("tool/post") == 0


async def test_child_plugin_disposes_with_parent() -> None:
    host = PluginHost()
    child_cleaned: List[str] = []

    def child_apply(ctx: Any) -> None:
        ctx.effect(lambda: (lambda: child_cleaned.append("child")))

    def parent_apply(ctx: Any) -> None:
        ctx.plugin("child", child_apply)

    parent = host.load("parent", parent_apply)
    await parent.start()
    await host.get("child").start()  # type: ignore[union-attr]

    await parent.dispose()

    assert child_cleaned == ["child"]
    assert host.get("child").state is FiberState.DISPOSED  # type: ignore[union-attr]


async def test_duplicate_load_rejected() -> None:
    host = PluginHost()
    host.load("dup", lambda _ctx: None)
    with pytest.raises(FiberStateError):
        host.load("dup", lambda _ctx: None)


async def test_unload_removes_fiber_and_detaches_watcher() -> None:
    host = PluginHost()
    release = host.services.provide("tools", object())
    fiber = host.load("gone", lambda _ctx: None, inject=["tools"])
    await fiber.start()

    await host.unload("gone")

    assert host.get("gone") is None
    release()
    await _settle()
    assert fiber.state is FiberState.DISPOSED


async def test_state_change_listener_receives_transitions() -> None:
    host = PluginHost()
    states: List[FiberState] = []
    off = host.on_state_change(lambda _pid, state: states.append(state))

    fiber = host.load("plain", lambda _ctx: None)
    await fiber.start()
    off()

    assert states == [FiberState.LOADING, FiberState.ACTIVE]


async def test_shutdown_disposes_everything() -> None:
    host = PluginHost()
    cleaned: List[str] = []

    def apply(ctx: Any) -> None:
        ctx.effect(lambda: (lambda: cleaned.append(ctx.plugin_id)))

    host.load("a", apply)
    host.load("b", apply)
    await host.start_all()

    await host.shutdown()

    assert sorted(cleaned) == ["a", "b"]
    assert host.states() == {}


async def test_dispose_error_is_wrapped() -> None:
    host = PluginHost()

    def bad_disposer() -> None:
        raise RuntimeError("cleanup failed")

    def apply(ctx: Any) -> None:
        ctx.effect(lambda: bad_disposer)

    fiber = host.load("bad-cleanup", apply)
    await fiber.start()

    with pytest.raises(FiberError):
        await fiber.dispose()
