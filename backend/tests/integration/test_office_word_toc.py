"""Integration tests for the Word TOC field (Round 13).

Covers: TOC field insertion (position after title / before body, instr
switches, placeholder text), zero change when toc is absent, level-order
validation, the paired linter rule (toc/presence), and the writing-skill
workflows advertising the repair tool (Round 12 closure).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from pydantic import ValidationError

from backend.office.models import OfficeWordGenerateRequest, WordFormatSpec, WordTocSpec
from backend.office.word import generate_docx
from backend.office.word_lint import lint_docx

_SHIPPED = Path(__file__).parents[2] / "skills" / "skill_md" / "shipped"


def _generate(tmp_path: Path, name: str, spec: dict, **kwargs) -> Path:
    req = OfficeWordGenerateRequest(
        workspace_path="",
        filename=name,
        title="测试文档",
        format_spec=spec,
        **kwargs,
    )
    return generate_docx(req, output_dir=str(tmp_path))


def _toc_instrs(doc: Document) -> list:
    return [
        fld.get(qn("w:instr"))
        for p in doc.paragraphs
        for fld in p._p.findall(".//" + qn("w:fldSimple"))
        if (fld.get(qn("w:instr")) or "").startswith("TOC")
    ]


# ──────────────────────────────────────────────────────────────────────
# Generation
# ──────────────────────────────────────────────────────────────────────


def test_toc_field_inserted_after_title_before_body(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        "toc.docx",
        {"toc": {}},
        paragraphs=[{"text": "引言", "heading": "h1"}, {"text": "正文"}],
    )
    doc = Document(str(path))
    texts = [p.text for p in doc.paragraphs]
    # 布局: 标题 / "目录"标题 / TOC 域段 / 分页段 / 正文...
    assert texts[0] == "测试文档"
    assert texts[1] == "目录"
    assert texts[4] == "引言"

    instrs = _toc_instrs(doc)
    assert instrs == ['TOC \\o "1-3" \\h \\z \\u']
    # 占位文本在 fldSimple 内嵌 run 中（paragraph.text 不聚合域内文本）
    fld = doc.paragraphs[2]._p.find(".//" + qn("w:fldSimple"))
    assert fld is not None
    placeholder = fld.find(qn("w:r") + "/" + qn("w:t"))
    assert placeholder is not None
    assert placeholder.text.startswith("（目录：")


def test_toc_levels_mapping_and_custom_texts(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        "toc2.docx",
        {
            "toc": {
                "heading_text": "目 录",
                "levels": "2-4",
                "placeholder_text": "请在渲染器中更新域",
            }
        },
        paragraphs=[{"text": "正文"}],
    )
    doc = Document(str(path))
    assert _toc_instrs(doc) == ['TOC \\o "2-4" \\h \\z \\u']
    assert doc.paragraphs[1].text == "目 录"
    fld = doc.paragraphs[2]._p.find(".//" + qn("w:fldSimple"))
    placeholder = fld.find(qn("w:r") + "/" + qn("w:t"))
    assert placeholder.text == "请在渲染器中更新域"


def test_no_toc_keeps_layout_unchanged(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        "plain.docx",
        {},
        paragraphs=[{"text": "引言", "heading": "h1"}],
    )
    doc = Document(str(path))
    texts = [p.text for p in doc.paragraphs]
    assert texts == ["测试文档", "引言"]
    assert _toc_instrs(doc) == []


def test_toc_levels_validation() -> None:
    with pytest.raises(ValidationError):
        WordTocSpec(levels="3-1")  # 起始大于结束
    with pytest.raises(ValidationError):
        WordTocSpec(levels="0-3")  # 级别从 1 起
    spec = WordFormatSpec(toc={"levels": "1-2"})
    assert spec.toc is not None
    assert spec.toc.level_range() == (1, 2)


# ──────────────────────────────────────────────────────────────────────
# Paired linter rule
# ──────────────────────────────────────────────────────────────────────


def test_linter_toc_presence(tmp_path: Path) -> None:
    path = _generate(tmp_path, "toc.docx", {"toc": {}}, paragraphs=[{"text": "正文"}])
    result = lint_docx(path, WordFormatSpec(**{"toc": {}}))
    assert result.ok
    assert "toc" in result.checked_rules

    # 反例：要求有目录但文档没有
    plain = _generate(tmp_path, "plain.docx", {}, paragraphs=[{"text": "正文"}])
    result = lint_docx(plain, WordFormatSpec(**{"toc": {}}))
    issues = [i for i in result.issues if i.rule_id == "toc/presence"]
    assert issues
    assert issues[0].severity == "error"

    # 不要求目录时不产生该规则
    result = lint_docx(plain, WordFormatSpec())
    assert "toc" not in result.checked_rules


# ──────────────────────────────────────────────────────────────────────
# Skills advertise the repair tool (Round 12 closure)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("skill_name", ["paper-writing", "report-writing"])
def test_writing_skill_workflows_advertise_repair(skill_name: str) -> None:
    text = (_SHIPPED / skill_name / "SKILL.md").read_text(encoding="utf-8")
    assert "office_repair_word" in text, f"{skill_name} 自检步骤未接入自动修复"
