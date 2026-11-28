"""execute_code 子进程 RPC 的准入策略（spec §8.1 / B1）。

RPC 桥没有交互式审批通道，因此默认拒绝 EXECUTE 面；但文献链路
（backend/literature/sage_driver.py）依赖 browser_navigate / browser_snapshot，
它们被归为 EXECUTE —— 静态一刀切会让整条链路在子进程内必失败。
本测试钉住「白名单放行 + 非白名单仍拒」。
"""

import pytest

from backend.tools.execute_code_tool import (
    RPC_ALLOWED_EXECUTE_TOOLS,
    RPC_FORBIDDEN_TOOLS,
    _rpc_denial_reason,
)
from backend.tools.permissions import ToolCapability, classify_tool

pytestmark = pytest.mark.unit


def test_allowed_whitelist_covers_the_documented_browser_surface() -> None:
    expected = {
        "browser_cookies",
        "browser_downloads",
        "browser_interact",
        "browser_navigate",
        "browser_snapshot",
        "browser_tabs",
    }
    assert expected <= set(RPC_ALLOWED_EXECUTE_TOOLS)


def test_whitelisted_tools_are_allowed_over_rpc() -> None:
    for name in sorted(RPC_ALLOWED_EXECUTE_TOOLS):
        assert _rpc_denial_reason(name) is None, f"{name} 应可经 RPC 调用"


def test_non_whitelisted_execute_tools_are_still_denied() -> None:
    denied = [
        name
        for name in ("browser_launch", "browser_login", "bash", "skill")
        if classify_tool(name) is ToolCapability.EXECUTE
    ]
    for name in denied:
        assert name not in RPC_ALLOWED_EXECUTE_TOOLS
        assert _rpc_denial_reason(name) is not None, f"{name} 仍应被拒绝"


def test_forbidden_tools_stay_denied_even_if_whitelisted() -> None:
    assert "ask_user_question" in RPC_FORBIDDEN_TOOLS
    assert _rpc_denial_reason("ask_user_question") is not None
