"""Regression tests for memory_manager injection in production registration paths.

These tests pin the behavior required by the Win7 memory-manager/SSL fix plan:

- Every ``MemorySearchTool`` and ``MemorySaveTool`` created by ``SageAgent``
  or ``InprocToolAdapter`` must receive the agent's ``memory_manager`` (or the
  shared ``get_memory_manager()`` singleton for the adapter) before it can be
  invoked, instead of returning ``未初始化`` at runtime.
- Bare ``SageAgent`` (used by ``AgentTool`` sub-agents) must keep its
  no-memory lightweight contract: no memory tools registered, no manager
  injected.

The tests intentionally exercise the production constructors rather than
calling ``set_memory_manager()`` directly, so any future regression in the
injection path surfaces here instead of at agent runtime.
"""

from __future__ import annotations

import pytest

from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.core.legacy.agent import SageAgent
from backend.tools.memory_tool import MemorySaveTool, MemorySearchTool

pytestmark = pytest.mark.integration

# ToolRegistry.list() returns List[ToolSchema] (not tool instances), so to
# obtain the actual MemorySearchTool / MemorySaveTool instances we walk
# ``_tools.values()`` — the brief's allowed adaptation. Using a private
# attribute matches existing tests that already reach into the registry
# internals; do NOT introduce a new public API just for this test.
_MEMORY_TOOL_TYPES = (MemorySearchTool, MemorySaveTool)


def _memory_tool_instances(registry) -> list:
    return [
        tool
        for tool in registry._tools.values()
        if isinstance(tool, _MEMORY_TOOL_TYPES)
    ]


def test_non_bare_agent_injects_its_memory_manager():
    """Non-bare SageAgent must wire self.memory_manager into every registered memory tool."""
    agent = SageAgent(bare=False)

    memory_tools = _memory_tool_instances(agent.tool_registry)

    assert {type(tool) for tool in memory_tools} == set(_MEMORY_TOOL_TYPES)
    assert all(tool.memory is agent.memory_manager for tool in memory_tools)
    assert agent.memory_manager is not None


def test_bare_agent_does_not_register_memory_tools():
    """Bare SageAgent retains its lightweight contract: no memory tools, no manager."""
    agent = SageAgent(bare=True)

    memory_tools = _memory_tool_instances(agent.tool_registry)
    assert memory_tools == []
    assert agent.memory_manager is None


def test_inproc_adapter_injects_memory_manager():
    """InprocToolAdapter() default-construct path must wire the shared manager into memory tools.

    Constructed with no arguments so the constructor's ``register_all_tools``
    branch is exercised (i.e. we cover the same path the production wiring uses).
    """
    adapter = InprocToolAdapter()

    memory_tools = _memory_tool_instances(adapter._registry)

    assert {type(tool) for tool in memory_tools} == set(_MEMORY_TOOL_TYPES)
    assert all(tool.memory is not None for tool in memory_tools)
