# ruff: noqa: UP006, UP007, UP035, UP045
"""EventBus 单测：四模式语义、优先级、撤销、异常聚合、超时。"""

from __future__ import annotations

import asyncio
from typing import Any, List

import pytest

from backend.application.kernel.events import (
    EventBus,
    EventDispatchError,
    EventNameError,
    EventTimeoutError,
    validate_event_name,
)


class TestEmit:
    def test_runs_in_priority_then_registration_order(self) -> None:
        bus = EventBus()
        seen: List[str] = []
        bus.on("tool/post", lambda: seen.append("low"), priority=0)
        bus.on("tool/post", lambda: seen.append("high"), priority=10)
        bus.on("tool/post", lambda: seen.append("mid"), priority=5)

        bus.emit("tool/post")

        assert seen == ["high", "mid", "low"]

    def test_ignores_return_values(self) -> None:
        bus = EventBus()
        bus.on("x/y", lambda: "ignored")
        assert bus.emit("x/y") is None

    def test_aggregates_handler_errors_but_runs_all(self) -> None:
        bus = EventBus()
        seen: List[str] = []

        def boom() -> None:
            raise RuntimeError("bad")

        bus.on("x/y", lambda: seen.append("a"))
        bus.on("x/y", boom)
        bus.on("x/y", lambda: seen.append("b"))

        with pytest.raises(EventDispatchError) as excinfo:
            bus.emit("x/y")

        assert seen == ["a", "b"]
        assert isinstance(excinfo.value.errors[0], RuntimeError)

    def test_async_handler_on_emit_is_reported(self) -> None:
        bus = EventBus()

        async def handler() -> None:
            return None

        bus.on("x/y", handler)

        with pytest.raises(EventDispatchError) as excinfo:
            bus.emit("x/y")

        assert isinstance(excinfo.value.errors[0], TypeError)

    def test_no_listener_is_a_noop(self) -> None:
        EventBus().emit("nobody/home")


class TestBail:
    async def test_first_defined_value_wins(self) -> None:
        bus = EventBus()
        bus.on("guard", lambda: None)
        bus.on("guard", lambda: False)
        bus.on("guard", lambda: "blocked")

        assert await bus.bail("guard") == "blocked"

    async def test_default_when_nothing_defined(self) -> None:
        bus = EventBus()
        bus.on("guard", lambda: None)
        assert await bus.bail("guard", default="allow") == "allow"

    async def test_awaits_async_handlers(self) -> None:
        bus = EventBus()

        async def slow() -> str:
            await asyncio.sleep(0)
            return "late"

        bus.on("guard", slow)
        assert await bus.bail("guard") == "late"

    async def test_timeout(self) -> None:
        bus = EventBus()

        async def hang() -> None:
            await asyncio.sleep(5)

        bus.on("guard", hang)
        with pytest.raises(EventTimeoutError):
            await bus.bail("guard", timeout=0.05)

    async def test_serial_is_bail_alias(self) -> None:
        bus = EventBus()
        bus.on("approve", lambda: "ok")
        assert await bus.serial("approve") == "ok"


class TestWaterfall:
    async def test_handlers_wrap_downstream_result(self) -> None:
        bus = EventBus()

        async def add_bang(_text: str, nxt: Any) -> str:
            return (await nxt()) + "!"

        async def add_question(_text: str, nxt: Any) -> str:
            return (await nxt()) + "?"

        bus.on("tool/args", add_bang)
        bus.on("tool/args", add_question)

        result = await bus.waterfall("tool/args", "hi", initial="hi")
        assert result == "hi?!"

    async def test_skipping_next_short_circuits(self) -> None:
        bus = EventBus()
        reached: List[str] = []

        async def blocker(_text: str, _nxt: Any) -> str:
            return "blocked"

        async def downstream(_text: str, nxt: Any) -> str:
            reached.append("downstream")
            return await nxt()

        bus.on("tool/args", blocker, priority=10)
        bus.on("tool/args", downstream, priority=0)

        assert await bus.waterfall("tool/args", "hi", initial="hi") == "blocked"
        assert reached == []

    async def test_empty_chain_returns_initial(self) -> None:
        bus = EventBus()
        assert await bus.waterfall("nothing/here", initial=42) == 42

    async def test_timeout(self) -> None:
        bus = EventBus()

        async def hang(_text: str, _nxt: Any) -> None:
            await asyncio.sleep(5)

        bus.on("tool/args", hang)
        with pytest.raises(EventTimeoutError):
            await bus.waterfall("tool/args", "hi", timeout=0.05)


class TestRegistration:
    def test_disposer_removes_handler(self) -> None:
        bus = EventBus()
        off = bus.on("x/y", lambda: None)
        assert bus.handler_count("x/y") == 1
        off()
        assert bus.handler_count("x/y") == 0

    def test_off_by_handler(self) -> None:
        bus = EventBus()

        def handler() -> None:
            return None

        bus.on("x/y", handler)
        assert bus.off("x/y", handler) == 1
        assert bus.off("x/y", handler) == 0

    def test_event_names_snapshot(self) -> None:
        bus = EventBus()
        bus.on("b/b", lambda: None)
        bus.on("a/a", lambda: None)
        assert bus.event_names() == ["a/a", "b/b"]

    def test_non_callable_handler_rejected(self) -> None:
        with pytest.raises(TypeError):
            EventBus().on("x/y", "not-callable")  # type: ignore[arg-type]


class TestEventNameValidation:
    @pytest.mark.parametrize("name", ["tool/pre", "agent/request", "session/event", "PreToolUse"])
    def test_valid_names(self, name: str) -> None:
        assert validate_event_name(name) == name

    @pytest.mark.parametrize("name", ["", "has space", "/leading", "trailing/", "bad!name"])
    def test_invalid_names(self, name: str) -> None:
        with pytest.raises(EventNameError):
            validate_event_name(name)
