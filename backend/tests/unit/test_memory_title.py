"""记忆标题推导工具（backend.memory.title_text）测试。

2026-11-17 记忆详情化：写入/读取路径的确定性标题兜底。
与会话标题生成（backend.chat.title_generator，LLM 驱动）职责不同：
本模块不调用 LLM，只做可预测的文本压缩。
"""

from __future__ import annotations

import pytest

from backend.memory.title_text import TITLE_MAX_LENGTH, derive_title

pytestmark = pytest.mark.unit


def test_skips_leading_blank_lines() -> None:
    assert derive_title("\n\n  用户偏好 TypeScript  ") == "用户偏好 TypeScript"


def test_strips_markdown_prefixes() -> None:
    assert derive_title("## 项目约束说明") == "项目约束说明"
    assert derive_title("- 使用 pnpm 管理依赖") == "使用 pnpm 管理依赖"
    assert derive_title("1. 先做测试后写实现") == "先做测试后写实现"


def test_collapses_whitespace() -> None:
    assert derive_title("用户   喜欢\t\tPython") == "用户 喜欢 Python"


def test_truncates_long_titles_with_ellipsis() -> None:
    title = derive_title("长" * (TITLE_MAX_LENGTH + 20))
    assert len(title) <= TITLE_MAX_LENGTH
    assert title.endswith("…")


def test_empty_content_falls_back_to_placeholder() -> None:
    assert derive_title("") == "无标题"
    assert derive_title(None) == "无标题"
    assert derive_title("   \n  ") == "无标题"
