"""Shipped writing skills (Round 11): paper-writing / report-writing.

Covers the SKILL.md layer only (pure markdown, no Python code paths):

1. shipped-dir discovery — the two new skills are discovered by the
   package-shipped directory scan and their frontmatter parses cleanly;
2. no name conflicts with the existing shipped skill (academic-search);
3. auto-activation — a paper-writing message activates paper-writing, a
   report-writing message activates report-writing, unrelated messages
   activate neither.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.skill_md.auto_activation import auto_activate
from backend.skills.skill_md.frontmatter import parse as parse_frontmatter
from backend.skills.skill_md.loader import _discover_shipped_dir
from backend.skills.skill_md.skill import SkillMdDocument

pytestmark = pytest.mark.unit

_SHIPPED = _discover_shipped_dir()


def _load_doc(skill_dir: Path) -> SkillMdDocument:
    """解析单个 shipped SKILL.md 为 SkillMdDocument（name 以目录名为准）。"""
    front, body = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    return SkillMdDocument(
        name=str(front.get("name") or skill_dir.name),
        description=str(front.get("description") or ""),
        when_to_use=str(front.get("when_to_use") or ""),
        allowed_tools=tuple(front.get("allowed-tools") or []),
        body=body,
        base_dir=skill_dir,
    )


def _shipped_docs() -> dict:
    """解析 shipped 目录下全部 SKILL.md，返回 name → SkillMdDocument。"""
    assert _SHIPPED is not None, "shipped 目录应存在"
    docs = {}
    for skill_dir in sorted(_SHIPPED.iterdir()):
        if (skill_dir / "SKILL.md").is_file():
            doc = _load_doc(skill_dir)
            docs[doc.name] = doc
    return docs


def _auto_activation_names(message: str) -> set:
    assert _SHIPPED is not None
    result = auto_activate(message, list(_shipped_docs().values()))
    return set(result.names)


# ──────────────────────────────────────────────────────────────────────
# Discovery + frontmatter
# ──────────────────────────────────────────────────────────────────────


def test_shipped_writing_skills_discovered() -> None:
    docs = _shipped_docs()
    assert {"paper-writing", "report-writing", "academic-search"} <= set(docs)


def test_frontmatter_fields_valid() -> None:
    docs = _shipped_docs()
    for name in ("paper-writing", "report-writing"):
        front = docs[name]
        assert front.name == name
        assert front.description, f"{name} 缺 description"
        assert front.when_to_use, f"{name} 缺 when_to_use"
        allowed = front.allowed_tools or []
        assert allowed, f"{name} 缺 allowed-tools"


def test_no_name_conflict_with_existing_shipped() -> None:
    names = list(_SHIPPED.glob("*/SKILL.md"))
    assert len(names) == len({n.parent.name for n in names})


def test_body_documents_full_pipeline_tools() -> None:
    """技能正文必须把 Round 7-10 的关键工具面写进工作流。"""
    docs = _shipped_docs()
    paper = docs["paper-writing"]
    report = docs["report-writing"]
    for tool in ("office_create", "office_lint_word"):
        assert tool in paper.body, f"paper-writing 正文缺 {tool}"
        assert tool in report.body, f"report-writing 正文缺 {tool}"
    assert "office_parse_bibtex" in paper.body
    assert "office_update" in report.body


# ──────────────────────────────────────────────────────────────────────
# Auto activation
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("帮我写论文，题目是大模型幻觉", {"paper-writing"}),
        ("毕业论文第三章需要整理一下", {"paper-writing"}),
        ("期刊投稿的正文可以开始起草了", {"paper-writing"}),
        ("写一份项目阶段报告", {"report-writing"}),
        ("把这些材料整理成项目文档", {"report-writing"}),
        ("帮忙起草一份技术报告", {"report-writing"}),
    ],
)
def test_auto_activation_hits_expected_skill(message: str, expected: set) -> None:
    assert _auto_activation_names(message) == expected


def test_unrelated_message_activates_nothing() -> None:
    assert _auto_activation_names("今天天气怎么样") == set()
