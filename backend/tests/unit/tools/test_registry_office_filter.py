"""ToolRegistry schema-filter tests for office tools.

Covers:
- With no active context (None), tools marked ``requires_tool_context=True``
  are hidden from ``get_schemas_for_llm`` while normal tools remain visible.
- With an active context, both normal and office-only tools are visible.
- The legacy ``get_schemas_for_llm()`` call (no args) keeps returning all
  schemas (backwards-compatible behavior for callers that don't know about
  contexts).
- ``BaseTool.requires_tool_context`` defaults to ``False`` so existing tools
  are unaffected.
- ``get_schemas_for_llm(context=...)`` shape matches the existing
  flat ``{name, description, parameters}`` dict per tool.

These tests are written before the filtering logic lives in
``backend/tools/registry.py`` -- they will FAIL until the registry knows
about ``ToolExecutionContext`` and the ``requires_tool_context`` flag.
"""

from __future__ import annotations

import pytest

from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import ToolExecutionContext, reset_tool_context, set_tool_context
from backend.tools.registry import ToolRegistry

pytestmark = pytest.mark.unit


class _DummyTool(BaseTool):
    """Test tool that mimics the existing ``_DummyTool`` shape."""

    def __init__(self, name: str, description: str = "dummy"):
        super().__init__()
        self._n = name
        self._d = description

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._n,
            description=self._d,
            parameters={"type": "object", "properties": {}, "required": []},
        )

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, content={"ok": True})


class _OfficeTool(_DummyTool):
    """Office-scoped tool that requires a context to be visible to the LLM."""

    requires_tool_context = True


def _ctx(session_id: str = "sess-x") -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id=session_id,
        stream_id="stream-x",
        binding_generation=1,
        office_doc_scope=frozenset(),
    )


# ---------- BaseTool.requires_tool_context default ----------


def test_base_tool_requires_tool_context_default_is_false():
    """New BaseTool subclasses default to ``requires_tool_context = False``."""
    t = _DummyTool(name="plain")
    assert t.requires_tool_context is False


def test_office_subclass_overrides_to_true():
    """A subclass that sets ``requires_tool_context = True`` flips the flag."""
    t = _OfficeTool(name="office-tool")
    assert t.requires_tool_context is True


# ---------- Registry filter behavior ----------


def test_registry_no_context_hides_office_tools():
    """With context=None, office-only tools are hidden; normal tools visible."""
    reg = ToolRegistry()
    reg.register(_DummyTool(name="calculator"))
    reg.register(_DummyTool(name="memory_search"))
    reg.register(_OfficeTool(name="office_read"))

    schemas = reg.get_schemas_for_llm()  # legacy call, context defaults to None
    names = {s["name"] for s in schemas}
    assert "calculator" in names
    assert "memory_search" in names
    assert "office_read" not in names


def test_registry_with_context_exposes_office_tools():
    """With an active context, office tools are visible alongside normal tools."""
    reg = ToolRegistry()
    reg.register(_DummyTool(name="calculator"))
    reg.register(_OfficeTool(name="office_read"))
    reg.register(_OfficeTool(name="office_write"))

    ctx = _ctx()
    schemas = reg.get_schemas_for_llm(context=ctx)
    names = {s["name"] for s in schemas}
    assert names == {"calculator", "office_read", "office_write"}


def test_registry_with_context_does_not_hide_normal_tools():
    """An active context never hides a normal tool. Sanity check."""
    reg = ToolRegistry()
    reg.register(_DummyTool(name="web_search"))
    reg.register(_DummyTool(name="terminal"))

    ctx = _ctx()
    schemas = reg.get_schemas_for_llm(context=ctx)
    names = {s["name"] for s in schemas}
    assert names == {"web_search", "terminal"}


def test_registry_filter_uses_current_tool_context_when_context_arg_none():
    """When ``context=None`` is passed explicitly, the registry uses the
    ContextVar (not the legacy compat path). ``current_tool_context()``
    returns None outside any set block, so the filter hides office tools.
    """
    reg = ToolRegistry()
    reg.register(_DummyTool(name="calculator"))
    reg.register(_OfficeTool(name="office_read"))

    schemas = reg.get_schemas_for_llm(context=None)
    names = {s["name"] for s in schemas}
    assert names == {"calculator"}


def test_registry_filter_uses_current_context_when_no_arg_given():
    """The no-arg call delegates to ``current_tool_context()``. With an
    active context, office tools appear.
    """
    reg = ToolRegistry()
    reg.register(_DummyTool(name="calculator"))
    reg.register(_OfficeTool(name="office_read"))

    ctx = _ctx()
    token = set_tool_context(ctx)
    try:
        # No explicit context kwarg -- relies on ContextVar lookup.
        schemas = reg.get_schemas_for_llm()
        names = {s["name"] for s in schemas}
        assert "office_read" in names
        assert "calculator" in names
    finally:
        reset_tool_context(token)


# ---------- Shape preservation ----------


def test_registry_get_schemas_for_llm_returns_flat_dicts():
    """Each schema dict carries name/description/parameters, regardless of filter."""
    reg = ToolRegistry()
    reg.register(_DummyTool(name="alpha", description="alpha tool"))
    reg.register(_OfficeTool(name="beta", description="beta tool"))

    ctx = _ctx()
    schemas = reg.get_schemas_for_llm(context=ctx)
    assert len(schemas) == 2
    for s in schemas:
        assert set(s.keys()) == {"name", "description", "parameters"}
        assert s["parameters"]["type"] == "object"


def test_registry_empty_returns_empty_list():
    """An empty registry returns an empty list (no context arg needed)."""
    reg = ToolRegistry()
    assert reg.get_schemas_for_llm() == []
    assert reg.get_schemas_for_llm(context=None) == []
    assert reg.get_schemas_for_llm(context=_ctx()) == []


# ---------- Execution lookup remains available ----------


def test_registry_get_returns_office_tool_even_without_context():
    """The filter only affects the LLM-facing schema list. ``get(name)`` for
    execution is not gated by the filter, so wrappers can still do their
    fail-closed context checks before calling ``execute()``.
    """
    reg = ToolRegistry()
    office = _OfficeTool(name="office_read")
    reg.register(office)

    # No context -> office tool is hidden from the LLM, but still resolvable.
    assert reg.get("office_read") is office
    assert reg.exists("office_read") is True
    # and is hidden from the LLM-facing schema list.
    assert all(s["name"] != "office_read" for s in reg.get_schemas_for_llm())
