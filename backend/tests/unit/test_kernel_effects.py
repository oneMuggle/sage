# ruff: noqa: UP006, UP007, UP035, UP045
"""EffectScope 单测：逆序、级联、异步并发、幂等、异常聚合。"""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from backend.application.kernel.effects import (
    EffectDisposalError,
    EffectScope,
    ScopeDisposedError,
)


async def test_sync_disposers_run_in_reverse_order() -> None:
    order: List[str] = []
    scope = EffectScope(label="t")
    scope.add(lambda: order.append("first"))
    scope.add(lambda: order.append("second"))
    scope.add(lambda: order.append("third"))

    await scope.dispose()

    assert order == ["third", "second", "first"]
    assert scope.disposed


async def test_child_scopes_dispose_before_parent() -> None:
    order: List[str] = []
    parent = EffectScope(label="parent")
    parent.add(lambda: order.append("parent"))
    child = parent.child("child")
    child.add(lambda: order.append("child"))
    grandchild = child.child("grandchild")
    grandchild.add(lambda: order.append("grandchild"))

    await parent.dispose()

    assert order == ["grandchild", "child", "parent"]
    assert child.disposed


async def test_async_disposers_run_concurrently() -> None:
    started: List[str] = []
    gate = asyncio.Event()

    def make(name: str):
        async def _dispose() -> None:
            started.append(name)
            if len(started) == 2:
                gate.set()
            # 若两者是串行执行，第一个会卡在 gate 上直到超时——由此证明并发。
            await asyncio.wait_for(gate.wait(), timeout=1.0)

        return _dispose

    scope = EffectScope(label="async")
    scope.add(make("a"))
    scope.add(make("b"))

    await asyncio.wait_for(scope.dispose(), timeout=2.0)
    assert sorted(started) == ["a", "b"]


async def test_dispose_is_idempotent() -> None:
    calls: List[int] = []
    scope = EffectScope()
    scope.add(lambda: calls.append(1))

    await scope.dispose()
    await scope.dispose()

    assert calls == [1]


async def test_register_after_dispose_raises() -> None:
    scope = EffectScope(label="closed")
    await scope.dispose()

    with pytest.raises(ScopeDisposedError):
        scope.add(lambda: None)
    with pytest.raises(ScopeDisposedError):
        scope.effect(lambda: (lambda: None))
    with pytest.raises(ScopeDisposedError):
        scope.child()


async def test_disposer_errors_are_aggregated_without_blocking_others() -> None:
    order: List[str] = []

    def boom() -> None:
        raise RuntimeError("kaboom")

    scope = EffectScope(label="bad")
    scope.add(lambda: order.append("ok-1"))
    scope.add(boom)
    scope.add(lambda: order.append("ok-2"))

    with pytest.raises(EffectDisposalError) as excinfo:
        await scope.dispose()

    assert len(excinfo.value.errors) == 1
    assert isinstance(excinfo.value.errors[0], RuntimeError)
    # 抛错的那个不阻断其余释放器
    assert order == ["ok-2", "ok-1"]
    assert scope.disposed


async def test_factory_must_return_callable() -> None:
    scope = EffectScope()
    with pytest.raises(TypeError):
        scope.effect(lambda: None)  # type: ignore[arg-type,return-value]


async def test_effect_returns_registered_disposer() -> None:
    calls: List[str] = []
    scope = EffectScope()
    disposer = scope.effect(lambda: (lambda: calls.append("done")))

    assert callable(disposer)
    assert scope.size == 1
    await scope.dispose()
    assert calls == ["done"]
    assert scope.size == 0


async def test_async_disposer_exception_is_collected_by_gather() -> None:
    async def boom() -> None:
        raise ValueError("async-kaboom")

    scope = EffectScope()
    scope.add(boom)

    with pytest.raises(EffectDisposalError) as excinfo:
        await scope.dispose()

    assert isinstance(excinfo.value.errors[0], ValueError)
