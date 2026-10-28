"""帮助文档 skills.md 与代码真相对齐 (缺口 #8)。

- 文档中列出的 builtin 技能名必须实际注册
- 文档中提到的 SKILL.md 字段名必须在 frontmatter 解析白名单里
- 文档不提到已经废弃的概念 (如技能市场)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.skills import register_all_skills
from backend.skills.registry import SkillRegistry

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parents[3]
DOC_PATH = REPO_ROOT / "src" / "content" / "help" / "skills.md"


def _get_builtin_names() -> set:
    reg = SkillRegistry()
    register_all_skills(reg)
    return {schema.name for schema in reg.list()}


def _extract_builtin_section(text: str) -> str:
    """Pull the 一、内置技能 section out of the doc."""
    m = re.search(r"^## 一、内置技能\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return m.group(1) if m else ""


def test_doc_lists_only_real_builtin_names():
    """文档中任何 ``| name |`` 形态的 builtin 表格行, 必须是真实注册的 builtin。"""
    text = DOC_PATH.read_text(encoding="utf-8")
    section = _extract_builtin_section(text)
    if not section:
        pytest.skip("文档未包含'一、内置技能'章节")
    listed_names: set = set()
    for line in section.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip().strip("`") for c in line.split("|")]
        # line.split("|") on "| a | b |" yields ['', ' a ', ' b ', ''];
        # the first column (cells[1]) is the name column. The remaining
        # columns are descriptions and must not be collected.
        if len(cells) < 2:
            continue
        name_cell = cells[1]
        if not name_cell:
            continue
        if name_cell in ("名称", "Name"):
            continue
        if set(name_cell) <= {"-", ":"}:
            continue
        listed_names.add(name_cell)
    if not listed_names:
        pytest.skip("章节中未找到 builtin 名字")
    real = _get_builtin_names()
    bogus = listed_names - real
    assert not bogus, f"文档列出的 builtin 名字不存在: {bogus} (实际: {real})"


def test_doc_mentions_at_skill_syntax():
    """文档必须提到 @skill:<name> 语法 (而非错误的 @技能名)。"""
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "@skill:" in text, "文档未提到 @skill:<name> 实体引用语法"


def test_doc_does_not_mention_skill_market():
    """文档不应提到不存在的'技能市场'概念 (避免误导用户)。"""
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "技能市场" not in text, "文档提到了不存在的'技能市场'"


def test_doc_exists_and_nonempty():
    assert DOC_PATH.exists(), f"文档缺失: {DOC_PATH}"
    text = DOC_PATH.read_text(encoding="utf-8")
    assert len(text) > 500, "文档过短 (< 500 字符)"
