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


def test_primary_and_researcher_profiles_include_browser_login():
    """primary 和 researcher 的白名单必须包含 browser_login 工具。

    用户在主聊天界面与 primary agent 交互，当网页被拦截（login_wall）时，
    primary 必须能看见并调用 browser_login 弹出浏览器辅助用户登录。
    """
    from backend.agents.profiles import _PRIMARY_SEED_TOOLS, create_default_agents

    assert "browser_login" in _PRIMARY_SEED_TOOLS, (
        "primary 白名单缺 browser_login — LLM 在主聊天界面无法协助用户登录站点"
    )

    defaults = {a.id: a for a in create_default_agents()}
    assert "browser_login" in defaults["primary"].tools
    assert "browser_login" in defaults["researcher"].tools
    assert "browser_login" in defaults["coder"].tools


def test_primary_profile_includes_ask_user_question():
    """primary (coordinator) 的 seed 白名单必须包含 ask_user_question。

    2026-10-28: 此前该工具仅在 ppt-maker profile 中可见，用户抱怨
    "LLM 遇到问题不方便与我交互"。将其加入 _PRIMARY_SEED_TOOLS，
    让默认 primary agent 也能在任务不明确时主动向用户提问。
    """
    from backend.agents.profiles import _PRIMARY_SEED_TOOLS, create_default_agents

    assert "ask_user_question" in _PRIMARY_SEED_TOOLS, (
        "primary 白名单缺 ask_user_question — LLM 无法主动向用户提问澄清需求"
    )

    defaults = {a.id: a for a in create_default_agents()}
    assert "ask_user_question" in defaults["primary"].tools


# 2026-11-17 feat/controlled-browser-use (M1 收尾): 主对话直接完成
# 导航→观察→交互→下载 循环。browser_launch 是高级入口（navigate 会自动
# 拉起），不进 primary。
_PRIMARY_BROWSER_USE_TOOLS = {
    "browser_navigate",
    "browser_snapshot",
    "browser_interact",
    "browser_screenshot",
    "browser_tabs",
    "browser_downloads",
    "browser_close",
    "browser_login",
}


def test_primary_profile_includes_browser_use_loop():
    """primary seed 与默认 profile 必须含完整 browser use 工具组（不含 launch）。"""
    from backend.agents.profiles import _PRIMARY_SEED_TOOLS, create_default_agents

    assert set(_PRIMARY_SEED_TOOLS) >= _PRIMARY_BROWSER_USE_TOOLS, (
        "primary seed 缺浏览器工具组 — 主对话无法完成 browser use 循环"
    )
    # browser_launch 不进 primary —— navigate 会自动拉起浏览器。
    assert "browser_launch" not in _PRIMARY_SEED_TOOLS, (
        "browser_launch 不应进 primary（navigate 会自动拉起）"
    )

    defaults = {a.id: a for a in create_default_agents()}
    primary_tools = set(defaults["primary"].tools)
    assert primary_tools >= _PRIMARY_BROWSER_USE_TOOLS
    assert "browser_launch" not in primary_tools


def test_researcher_profile_includes_browser_evidence_tools():
    """researcher 补截图/下载/标签三件（动态页面委派取证全链路）。"""
    from backend.agents.profiles import create_default_agents

    defaults = {a.id: a for a in create_default_agents()}
    researcher_tools = set(defaults["researcher"].tools)

    for tool in ("browser_screenshot", "browser_downloads", "browser_tabs"):
        assert tool in researcher_tools, f"researcher 缺 {tool}"


def test_subagent_whitelist_gets_screenshot_and_downloads_not_tabs():
    """子代理白名单补 screenshot/downloads（READ），但不给 tabs（最小权限）。"""
    from backend.tools.agent_tool import SUBAGENT_TOOL_WHITELIST

    whitelist = set(SUBAGENT_TOOL_WHITELIST)
    assert "browser_screenshot" in whitelist
    assert "browser_downloads" in whitelist
    assert "browser_tabs" not in whitelist, (
        "browser_tabs 不应下放子代理 — 多标签归主对话/researcher 统筹"
    )
    # 既有浏览器通道不被误删
    for tool in (
        "browser_launch",
        "browser_navigate",
        "browser_snapshot",
        "browser_interact",
        "browser_cookies",
        "browser_close",
    ):
        assert tool in whitelist


# 2026-11-17 feat/controlled-browser-use (M1 收尾): 主对话直接完成
# 导航→观察→交互→下载 循环。browser_launch 是高级入口（navigate 会自动
# 拉起），不进 primary。
_PRIMARY_BROWSER_USE_TOOLS = {
    "browser_navigate",
    "browser_snapshot",
    "browser_interact",
    "browser_screenshot",
    "browser_tabs",
    "browser_downloads",
    "browser_close",
    "browser_login",
}


def test_primary_profile_includes_browser_use_loop():
    """primary seed 与默认 profile 必须含完整 browser use 工具组（不含 launch）。"""
    from backend.agents.profiles import _PRIMARY_SEED_TOOLS, create_default_agents

    assert set(_PRIMARY_SEED_TOOLS) >= _PRIMARY_BROWSER_USE_TOOLS, (
        "primary seed 缺浏览器工具组 — 主对话无法完成 browser use 循环"
    )
    # browser_launch 不进 primary —— navigate 会自动拉起浏览器。
    assert "browser_launch" not in _PRIMARY_SEED_TOOLS, (
        "browser_launch 不应进 primary（navigate 会自动拉起）"
    )

    defaults = {a.id: a for a in create_default_agents()}
    primary_tools = set(defaults["primary"].tools)
    assert primary_tools >= _PRIMARY_BROWSER_USE_TOOLS
    assert "browser_launch" not in primary_tools


def test_researcher_profile_includes_browser_evidence_tools():
    """researcher 补截图/下载/标签三件（动态页面委派取证全链路）。"""
    from backend.agents.profiles import create_default_agents

    defaults = {a.id: a for a in create_default_agents()}
    researcher_tools = set(defaults["researcher"].tools)

    for tool in ("browser_screenshot", "browser_downloads", "browser_tabs"):
        assert tool in researcher_tools, f"researcher 缺 {tool}"


def test_subagent_whitelist_gets_screenshot_and_downloads_not_tabs():
    """子代理白名单补 screenshot/downloads（READ），但不给 tabs（最小权限）。"""
    from backend.tools.agent_tool import SUBAGENT_TOOL_WHITELIST

    whitelist = set(SUBAGENT_TOOL_WHITELIST)
    assert "browser_screenshot" in whitelist
    assert "browser_downloads" in whitelist
    assert "browser_tabs" not in whitelist, (
        "browser_tabs 不应下放子代理 — 多标签归主对话/researcher 统筹"
    )
    # 既有浏览器通道不被误删
    for tool in (
        "browser_launch",
        "browser_navigate",
        "browser_snapshot",
        "browser_interact",
        "browser_cookies",
        "browser_close",
    ):
        assert tool in whitelist


