"""Orchestration stub routes (placeholder — implemented in Task 3).

Registers zero routes in this initial scaffold. Task 3 will populate this
function with the orchestration endpoints (5 routes per the plan).

Contract:
    register_orchestration_routes(registry: dict) -> None

    ``registry`` is a dict populated by chat.py / orchestration.py / etc.
    Keys are ``(method: str, path_regex: str)`` tuples, values are callables
    with signature ``fn(ctx: StubContext, body: dict, **path_groups) -> None``.
"""
from __future__ import annotations


def register_orchestration_routes(registry: dict) -> None:
    """Orchestration routes — implemented in Task 3."""
    pass
