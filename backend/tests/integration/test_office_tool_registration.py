"""Integration tests: Office Parity Batch-1 tool registration wiring.

把 6 个新 Office 工具（PDF 三类 + Word 模板两件套）钉在三条接线上：

1. ``domain.tool_names.OFFICE_TOOLS`` 包含全部 6 个新名字（primary 种子
   经 ``*OFFICE_TOOLS`` 继承）。
2. ``register_all_tools`` 把 6 个工具实际注册进 ToolRegistry（同时保证
   ``ALL_BUILTIN_TOOL_NAMES`` 清单不漂移 —— test_tool_names.py 交叉锁定）。
3. profile 白名单：primary / writer 全量包含；researcher / coder /
   memory_manager / reviewer 一个都没有。
4. registry 过滤语义：读三件（requires_tool_context=True）无绑定上下文时
   隐藏；写三件（file_path 模式）始终可见。
"""

from __future__ import annotations

import pytest

from backend.agents.profiles import create_default_agents
from backend.domain.tool_names import OFFICE_TOOLS
from backend.tools import ToolRegistry, register_all_tools
from backend.tools.context import ToolExecutionContext

pytestmark = pytest.mark.integration

#: 本批次新接入的 6 个工具名（与 tool_names.OFFICE_TOOLS 尾部对齐）
NEW_OFFICE_TOOLS = (
    "office_read_pdf",
    "office_generate_pdf",
    "office_read_pdf_form",
    "office_fill_pdf_form",
    "office_analyze_word_template",
    "office_fill_word_template",
)

#: 写三件 —— file_path 模式，无绑定上下文也可见
WRITE_MODE_TOOLS = frozenset(
    {"office_generate_pdf", "office_fill_pdf_form", "office_fill_word_template"}
)


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    register_all_tools(reg)
    return reg


@pytest.fixture()
def bound_ctx() -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id="sess-reg",
        stream_id="stream-reg",
        binding_generation=1,
        office_doc_scope=frozenset(),
    )


def _profile(agent_id: str):
    return next(p for p in create_default_agents() if p.id == agent_id)


def _visible_names(registry, ctx, allowed_tools):
    return {
        s["name"]
        for s in registry.get_schemas_for_llm(context=ctx, allowed_tools=allowed_tools)
    }


# ── 1. tool_names 清单 ────────────────────────────────────────────────


def test_new_names_present_in_office_tools_tuple():
    for name in NEW_OFFICE_TOOLS:
        assert name in OFFICE_TOOLS, f"{name} 未进入 OFFICE_TOOLS"


# ── 2. 实际注册面 ─────────────────────────────────────────────────────


def test_new_tools_registered_in_registry(registry):
    registered = set(registry.list_names())
    for name in NEW_OFFICE_TOOLS:
        assert name in registered, f"{name} 未注册进 ToolRegistry"


def test_new_tools_declare_expected_risk_and_context(registry):
    from backend.domain.risk import RiskClass

    read_tools = set(NEW_OFFICE_TOOLS) - WRITE_MODE_TOOLS
    for name in read_tools:
        tool = registry.get(name)
        assert tool.requires_tool_context is True, name
        assert tool.risk is RiskClass.READ, name
    for name in WRITE_MODE_TOOLS:
        tool = registry.get(name)
        assert tool.requires_tool_context is False, name
        assert tool.risk is RiskClass.WRITE_LOCAL, name


# ── 3. profile 白名单归属 ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "agent_id", ["primary", "writer"]
)
def test_primary_and_writer_include_new_tools(agent_id):
    tools = set(_profile(agent_id).tools)
    missing = [name for name in NEW_OFFICE_TOOLS if name not in tools]
    assert not missing, f"{agent_id} 缺少: {missing}"


def test_writer_still_has_no_office_delete():
    assert "office_delete" not in set(_profile("writer").tools)


@pytest.mark.parametrize(
    "agent_id", ["researcher", "coder", "memory_manager", "reviewer"]
)
def test_restricted_profiles_exclude_new_tools(agent_id):
    tools = set(_profile(agent_id).tools)
    leaked = [name for name in NEW_OFFICE_TOOLS if name in tools]
    assert not leaked, f"{agent_id} 不应看到: {leaked}"


# ── 4. registry 过滤语义 ──────────────────────────────────────────────


def test_bound_context_exposes_all_new_tools(registry, bound_ctx):
    visible = _visible_names(registry, bound_ctx, _profile("primary").tools)
    for name in NEW_OFFICE_TOOLS:
        assert name in visible, name


def test_no_context_hides_read_tools_but_keeps_write_tools(registry):
    visible = _visible_names(registry, None, _profile("primary").tools)
    for name in NEW_OFFICE_TOOLS:
        if name in WRITE_MODE_TOOLS:
            assert name in visible, name
        else:
            assert name not in visible, name
