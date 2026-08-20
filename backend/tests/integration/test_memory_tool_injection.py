"""Regression tests for memory_manager injection in production registration paths.

These tests pin the behavior required by the Win7 memory-manager/SSL fix plan:

- Every ``MemorySearchTool`` and ``MemorySaveTool`` created by ``SageAgent``
  or ``InprocToolAdapter`` must receive the agent's ``memory_manager`` (or the
  shared ``get_memory_manager()`` singleton for the adapter) before it can be
  invoked, instead of returning ``未初始化`` at runtime.
- Bare ``SageAgent`` (used by ``AgentTool`` sub-agents) must keep its
  no-memory lightweight contract: no memory tools registered, no manager
  injected.
- ``InprocToolAdapter`` must NOT silently mutate an externally-owned
  registry: callers that pre-register tools via ``register_all_tools``
  before passing the registry in retain ``memory is None`` on every
  memory tool.

The tests intentionally exercise the production constructors rather than
calling ``set_memory_manager()`` directly, so any future regression in the
injection path surfaces here instead of at agent runtime.
"""

from __future__ import annotations

import pytest

from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.core.legacy.agent import SageAgent
from backend.memory.registry import get_memory_manager
from backend.tools import ToolRegistry, register_all_tools
from backend.tools.memory_tool import MEMORY_TOOL_TYPES

pytestmark = pytest.mark.integration


def _memory_tool_instances(registry) -> list:
    """Return the actual ``MemorySearchTool`` / ``MemorySaveTool`` instances in ``registry``.

    ``ToolRegistry.list()`` returns ``List[ToolSchema]`` (not tool instances),
    so we walk registered names via the public API and unwrap each via
    ``get(name)`` to obtain the live object.
    """
    return [
        tool
        for name in registry.list_names()
        for tool in [registry.get(name)]
        if isinstance(tool, MEMORY_TOOL_TYPES)
    ]


def test_non_bare_agent_injects_its_memory_manager():
    """Non-bare SageAgent must wire self.memory_manager into every registered memory tool."""
    agent = SageAgent(bare=False)

    memory_tools = _memory_tool_instances(agent.tool_registry)

    assert {type(tool) for tool in memory_tools} == set(MEMORY_TOOL_TYPES)
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
    The identity assertion pins ``tool.memory is get_memory_manager()``:
    production must use the shared singleton, not re-construct a manager.
    """
    adapter = InprocToolAdapter()

    memory_tools = _memory_tool_instances(adapter._registry)

    assert {type(tool) for tool in memory_tools} == set(MEMORY_TOOL_TYPES)
    shared = get_memory_manager()
    assert all(tool.memory is shared for tool in memory_tools)


def test_inproc_adapter_does_not_mutate_externally_owned_registry():
    """Adapter must not silently inject manager into an externally-owned registry.

    Wiring an existing registry (already populated by ``register_all_tools``)
    through ``InprocToolAdapter(registry=existing)`` must leave every memory
    tool's ``memory`` attribute as ``None``. The adapter's injection contract
    only applies to the registry it constructs itself -- externally-owned
    registries retain caller-controlled state.
    """
    existing_registry = ToolRegistry()
    register_all_tools(existing_registry)

    # Sanity: memory tools are present and uninitialized before adapter wraps it.
    pre_memory_tools = _memory_tool_instances(existing_registry)
    assert pre_memory_tools, "pre-register_all_tools should have populated memory tools"
    assert all(tool.memory is None for tool in pre_memory_tools)

    InprocToolAdapter(registry=existing_registry)

    # Pin: no memory tool in the externally-owned registry has been mutated.
    post_memory_tools = _memory_tool_instances(existing_registry)
    assert all(tool.memory is None for tool in post_memory_tools)
