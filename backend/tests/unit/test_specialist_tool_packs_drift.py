# ruff: noqa: UP006, UP007, UP035
"""M2：前端专家能力包的工具名必须仍是后端内置工具清单的一部分。

``src/entities/specialist/toolCapabilities.ts`` 把工具名静态聚合为能力包；
后端改名/删除工具时前端不会编译报错，只会在运行时静默失配。本测试读取
两侧文本做漂移守卫：包内工具名 ⊆ ``_EXPECTED_ONLINE``，且除显式排除项
外所有内置工具都必须归入某个包（新增工具时必须归类，否则 CI 红灯）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Set

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKS_TS = _REPO_ROOT / "src" / "entities" / "specialist" / "toolCapabilities.ts"
_PARITY_PY = Path(__file__).resolve().parent / "test_tool_bundles_parity.py"

_PACK_TOOLS_BLOCK = re.compile(r"tools:\s*\[(.*?)\]", re.DOTALL)
_SINGLE_QUOTED = re.compile(r"'([a-z][a-z0-9_*]+)'")
_EXPECTED_BLOCK = re.compile(r"^_EXPECTED_ONLINE = \[(.*?)^\]", re.DOTALL | re.MULTILINE)
_DOUBLE_QUOTED = re.compile(r'"([a-z][a-z0-9_]+)"')

# office_delete 是执行面工具，刻意不放进办公包（需在高级白名单单独添加）。
_INTENTIONALLY_UNPACKED = {"office_delete"}


def _pack_tools() -> Set[str]:
    source = _PACKS_TS.read_text(encoding="utf-8")
    tools: Set[str] = set()
    for block in _PACK_TOOLS_BLOCK.findall(source):
        tools.update(_SINGLE_QUOTED.findall(block))
    return tools


def _builtin_tools() -> Set[str]:
    source = _PARITY_PY.read_text(encoding="utf-8")
    match = _EXPECTED_BLOCK.search(source)
    assert match is not None, "未能从黄金快照解析 _EXPECTED_ONLINE"
    return set(_DOUBLE_QUOTED.findall(match.group(1)))


def test_pack_file_declares_a_full_tool_set() -> None:
    assert _PACKS_TS.is_file()
    assert len(_pack_tools()) > 100


def test_pack_tools_exist_in_backend_registry() -> None:
    builtin = _builtin_tools()
    unknown = sorted(
        tool
        for tool in _pack_tools()
        if not tool.startswith("plugin__") and tool not in builtin
    )
    assert unknown == [], f"能力包引用了后端不存在的工具: {unknown}"


def test_plugin_pack_uses_only_the_global_wildcard() -> None:
    plugin_tools = {tool for tool in _pack_tools() if tool.startswith("plugin__")}
    assert plugin_tools == {"plugin__*"}


def test_every_builtin_tool_is_packed_or_explicitly_excluded() -> None:
    unpacked = _builtin_tools() - _pack_tools() - _INTENTIONALLY_UNPACKED
    assert unpacked == set(), (
        "以下内置工具未归入任何能力包；新工具请加入 toolCapabilities.ts "
        f"或显式排除: {sorted(unpacked)}"
    )
