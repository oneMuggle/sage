"""Memory stub routes (placeholder — implemented in Task 5).

Registers zero routes in this initial scaffold. Task 5 will populate this
function with the memory endpoints (4 routes per the plan).

Contract:
    register_memory_routes(registry: dict) -> None

    ``registry`` is a dict populated by chat.py / orchestration.py / etc.
    Keys are ``(method: str, path_regex: str)`` tuples, values are callables
    with signature ``fn(ctx: StubContext, body: dict, **path_groups) -> None``.
"""
from __future__ import annotations


def register_memory_routes(registry: dict) -> None:
    """Memory routes — implemented in Task 5."""
    pass
