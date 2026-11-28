"""用户可见文案不得指向不存在的工具（spec §8.2 / B2）。

`credential_set` 曾在 download_tool / web_tool 的 6 处错误文案里出现，
但全仓没有这个工具 —— 模型照做只会再失败一次。
"""

import re
from pathlib import Path

import pytest

from backend.tools import download_tool, web_tool

pytestmark = pytest.mark.unit

_TARGET_FILES = (download_tool, web_tool)


def _module_source(module) -> str:
    """读模块源码（用 Path 读文件，避免 ruff SIM115 的裸 open 告警）。"""
    return Path(str(module.__file__)).read_text(encoding="utf-8")


def test_no_user_visible_text_references_credential_set() -> None:
    """Guard against references to the phantom tool ``credential_set``.

    The regex must be specific to ``credential_set`` to avoid false positives
    from internal method names like ``_writeback_set_cookies`` or
    ``merge_set_cookies``.
    """
    pattern = re.compile(r"`?credential_set`?")
    offenders = []
    for module in _TARGET_FILES:
        source = _module_source(module)
        for match in pattern.finditer(source):
            offenders.append(f"{module.__name__}: {match.group(0)}")
    assert not offenders, (
        "文案引用了不存在的工具（模型会照做再失败一次）: " + ", ".join(offenders)
    )


def test_credential_set_is_not_referenced_anywhere_in_those_modules() -> None:
    for module in _TARGET_FILES:
        source = _module_source(module)
        assert "credential_set" not in source, (
            f"{module.__name__} 仍含 credential_set 文案"
        )
