"""BROWSER_TOOL_NAMES 与 domain/tool_names.BROWSER_TOOLS 必须集合相等。

spec §8.3（B3）：原实现手抄 10 项元组，漏掉 browser_list_accounts /
browser_switch_account，且既有断言只测成员存在、不比对元组，漂移不报错。
本文件把「单一事实源」钉成可执行断言。
"""

import pytest

from backend.domain import tool_names
from backend.tools import browser_tool
from backend.tools.permissions import TOOL_CAPABILITIES, ToolCapability

pytestmark = pytest.mark.unit


def test_browser_tool_names_matches_domain_registry() -> None:
    assert set(browser_tool.BROWSER_TOOL_NAMES) == set(tool_names.BROWSER_TOOLS)


def test_browser_tool_names_has_no_duplicates() -> None:
    names = list(browser_tool.BROWSER_TOOL_NAMES)
    assert len(names) == len(set(names)), f"BROWSER_TOOL_NAMES 存在重复项: {names}"


def test_every_domain_browser_tool_has_a_capability() -> None:
    missing = sorted(set(tool_names.BROWSER_TOOLS) - set(TOOL_CAPABILITIES))
    assert not missing, f"browser 工具缺能力登记: {missing}"
    for name in tool_names.BROWSER_TOOLS:
        assert TOOL_CAPABILITIES[name] in (
            ToolCapability.READ,
            ToolCapability.WRITE,
            ToolCapability.EXECUTE,
        )
