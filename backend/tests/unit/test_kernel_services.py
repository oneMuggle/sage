# ruff: noqa: UP006, UP007, UP035, UP045
"""ServiceRegistry 单测：提供/读取/冲突/变更通知/幂等撤销。"""

from __future__ import annotations

from typing import Any, List, Tuple

import pytest

from backend.application.kernel.services import (
    ServiceConflictError,
    ServiceError,
    ServiceNotFoundError,
    ServiceRegistry,
)
from backend.domain.plugin import PluginContractError


def test_provide_and_get() -> None:
    registry = ServiceRegistry()
    instance = object()
    registry.provide("tools", instance, owner="core")

    assert registry.get("tools") is instance
    assert registry.require("tools") is instance
    assert registry.has("tools")
    assert registry.names() == ["tools"]
    assert registry.owner_of("tools") == "core"
    assert registry.snapshot() == {"tools": "core"}


def test_get_missing_returns_none_but_require_raises() -> None:
    registry = ServiceRegistry()
    assert registry.get("absent") is None
    with pytest.raises(ServiceNotFoundError):
        registry.require("absent")


def test_conflict_raises() -> None:
    registry = ServiceRegistry()
    registry.provide("tools", object(), owner="a")
    with pytest.raises(ServiceConflictError) as excinfo:
        registry.provide("tools", object(), owner="b")
    assert excinfo.value.existing_owner == "a"
    assert excinfo.value.new_owner == "b"


def test_disposer_removes_service() -> None:
    registry = ServiceRegistry()
    release = registry.provide("tools", object())
    release()

    assert not registry.has("tools")
    assert registry.names() == []


def test_disposer_is_idempotent_and_cannot_remove_newer_provider() -> None:
    registry = ServiceRegistry()
    first = object()
    second = object()
    release_first = registry.provide("tools", first)
    release_first()

    registry.provide("tools", second)
    release_first()  # 旧释放器不得误删新提供者

    assert registry.get("tools") is second


def test_on_change_notifies_both_directions() -> None:
    registry = ServiceRegistry()
    events: List[Tuple[str, bool]] = []
    off = registry.on_change(lambda name, present: events.append((name, present)))

    release = registry.provide("llm", object())
    release()
    off()
    registry.provide("llm", object())

    assert events == [("llm", True), ("llm", False)]


def test_change_listener_failure_is_isolated() -> None:
    registry = ServiceRegistry()
    seen: List[str] = []

    def boom(_name: str, _present: bool) -> None:
        raise RuntimeError("subscriber down")

    registry.on_change(boom)
    registry.on_change(lambda name, present: seen.append(f"{name}={present}"))

    release = registry.provide("web", object())
    release()

    assert seen == ["web=True", "web=False"]


def test_replace_restores_previous_instance() -> None:
    registry = ServiceRegistry()
    original = object()
    replacement = object()
    registry.provide("llm", original, owner="builtin")

    release = registry.replace("llm", replacement, owner="override")
    assert registry.get("llm") is replacement
    assert registry.owner_of("llm") == "override"

    release()
    assert registry.get("llm") is original
    assert registry.owner_of("llm") == "builtin"


def test_missing_keeps_declaration_order() -> None:
    registry = ServiceRegistry()
    registry.provide("b", object())
    assert registry.missing(["b", "a", "c"]) == ["a", "c"]


def test_none_instance_rejected() -> None:
    with pytest.raises(ServiceError):
        ServiceRegistry().provide("tools", None)


def test_invalid_name_rejected() -> None:
    with pytest.raises(PluginContractError):
        ServiceRegistry().provide("bad name", object())


def test_clear_notifies_removals() -> None:
    registry = ServiceRegistry()
    events: List[Any] = []
    registry.on_change(lambda name, present: events.append((name, present)))
    registry.provide("a", object())
    registry.provide("b", object())

    registry.clear()

    assert registry.names() == []
    assert events == [("a", True), ("b", True), ("a", False), ("b", False)]
