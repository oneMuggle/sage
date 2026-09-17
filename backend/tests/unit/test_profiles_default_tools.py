"""alpha.36 (Bug #5): primary / coder profile 白名单必须包含沙箱代码执行工具。

根因：repl / execute_code 在 backend/tools/ 已实现、已注册到
_BUILTIN_TOOL_REGISTRY、domain/tool_names.SANDBOX_TOOLS 已声明，
但 profiles._PRIMARY_SEED_TOOLS / _CODER_SEED_TOOLS 从未引用 ——
LLM 根本看不见这两个工具，用户抱怨"代码执行工具没法执行代码"。

本测试防止再次漂移。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_primary_profile_includes_repl_and_execute_code():
    """primary (coordinator) 的 seed 白名单必须包含 repl + execute_code。"""
    from backend.agents.profiles import _PRIMARY_SEED_TOOLS

    assert "repl" in _PRIMARY_SEED_TOOLS, (
        "alpha.36 (Bug #5): primary 白名单缺 repl — LLM 无法使用持久 Python 会话"
    )
    assert "execute_code" in _PRIMARY_SEED_TOOLS, (
        "alpha.36 (Bug #5): primary 白名单缺 execute_code — LLM 无法使用 zero-context RPC"
    )
    # calculator 已在 _PRIMARY_CORE_TOOLS，不应重复（set 语义）
    assert _PRIMARY_SEED_TOOLS.count("calculator") == 1


def test_coder_profile_includes_repl_and_execute_code():
    """coder (executor) 的 seed 白名单必须包含 repl + execute_code。"""
    from backend.agents.profiles import _CODER_SEED_TOOLS

    assert "repl" in _CODER_SEED_TOOLS, (
        "alpha.36 (Bug #5): coder 白名单缺 repl — coder 作为 executor 必须能用持久 Python 会话"
    )
    assert "execute_code" in _CODER_SEED_TOOLS, (
        "alpha.36 (Bug #5): coder 白名单缺 execute_code"
    )


def test_create_default_agents_primary_and_coder_have_sandbox_tools():
    """端到端：create_default_agents() 输出的 primary / coder 工具列表包含沙箱工具。"""
    from backend.agents.profiles import create_default_agents

    agents = create_default_agents()
    by_id = {a.id: a for a in agents}

    assert "primary" in by_id
    assert "coder" in by_id

    primary_tools = set(by_id["primary"].tools)
    coder_tools = set(by_id["coder"].tools)

    assert "repl" in primary_tools
    assert "execute_code" in primary_tools
    assert "repl" in coder_tools
    assert "execute_code" in coder_tools


def test_all_builtin_tool_names_still_includes_sandbox_tools():
    """ALL_BUILTIN_TOOL_NAMES 防漂移校验仍包含 SANDBOX_TOOLS（baseline 守卫）。"""
    from backend.domain.tool_names import ALL_BUILTIN_TOOL_NAMES, SANDBOX_TOOLS

    for name in SANDBOX_TOOLS:
        assert name in ALL_BUILTIN_TOOL_NAMES, (
            f"ALL_BUILTIN_TOOL_NAMES 漏 {name} — 防漂移校验失效"
        )
