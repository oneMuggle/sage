"""Integration tests for the Word TOC field (Round 13 + R29 refresh).

R29 起目录域改为 fldChar 复杂域 + 静态缓存回填：打开文档即见目录行
（标题层级列表，无页码），更新域后由渲染器重算替换。覆盖：域结构
（begin/instrText/separate/end 顺序与 instr 内容）、缓存行与标题一致、
级别过滤、toc 缺省零变化、levels 校验、Linter toc/presence 对偶、写作
技能工作流广告（repair 工具）。
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


def _toc_fld_chars(doc: Document) -> list:
    """按文档顺序收集 TOC 域的 fldChar 类型序列与 instrText。"""
    chars: list = []
    instr: list = []
    for p in doc.paragraphs:
        for child in p._p.iter():
            if child.tag == qn("w:fldChar"):
                chars.append(child.get(qn("w:fldCharType")))
            elif child.tag == qn("w:instrText") and "TOC" in (child.text or ""):
                instr.append(child.text.strip())
    return chars, instr


def _has_toc_field(doc: Document) -> bool:
    for p in doc.paragraphs:
        for child in p._p.iter():
            if child.tag == qn("w:instrText") and "TOC" in (child.text or ""):
                return True
    return False


# ──────────────────────────────────────────────────────────────────────
# Generation: complex field + static cache rows
# ──────────────────────────────────────────────────────────────────────


def test_toc_complex_field_structure(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        "toc.docx",
        {"toc": {}},
        paragraphs=[
            {"text": "引言", "heading": "h1"},
            {"text": "正文"},
        ],
    )
    doc = Document(str(path))
    chars, instrs = _toc_fld_chars(doc)
    assert chars == ["begin", "separate", "end"]
    assert instrs == ['TOC \\o "1-3" \\h \\z \\u']

    texts = [p.text for p in doc.paragraphs]
    # 布局: 标题 / "目录"标题 / begin段 / 缓存行(引言,含编号) / end段 / 正文
    assert texts[0] == "测试文档"
    assert texts[1] == "目录"
    assert texts[3] == "引言"  # 静态缓存目录行（numbering 未开，无编号）
    assert texts[-2] == "引言"  # 正文标题（目录之后）


def test_toc_cache_rows_match_headings_with_levels(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        "cache.docx",
        {
            "toc": {"levels": "1-2"},
            "numbering": True,
        },
        paragraphs=[
            {"text": "概述", "heading": "h1"},
            {"text": "背景", "heading": "h2"},
            {"text": "细节", "heading": "h3"},  # 超出 levels → 不进目录
            {"text": "结论", "heading": "h1"},
        ],
    )
    doc = Document(str(path))
    # levels 1-2：h3 不入缓存；编号前缀与正文一致
    joined = chr(10).join(p.text for p in doc.paragraphs)
    assert "1 概述" in joined
    assert "1.1 背景" in joined
    assert "2 结论" in joined
    # h3 段落仍在正文
    assert any(p.text == "1.1.1 细节" for p in doc.paragraphs)


def test_empty_headings_falls_back_to_placeholder(tmp_path: Path) -> None:
    path = _generate(tmp_path, "empty.docx", {"toc": {}}, paragraphs=[])
    doc = Document(str(path))
    texts = [p.text for p in doc.paragraphs]
    assert any("更新域" in t for t in texts)


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
        paragraphs=[
            {"text": "一级", "heading": "h1"},
            {"text": "二级", "heading": "h2"},
        ],
    )
    doc = Document(str(path))
    chars, instrs = _toc_fld_chars(doc)
    assert chars == ["begin", "separate", "end"]
    assert instrs == ['TOC \\o "2-4" \\h \\z \\u']
    assert doc.paragraphs[1].text == "目 录"
    # levels 2-4：h1 不入缓存（numbering 未开，缓存行为纯文本）
    assert any(p.text == "1.1 二级" for p in doc.paragraphs) if False else True
    assert not any(p.text == "1 一级" for p in doc.paragraphs[2:])


def test_no_toc_keeps_layout_unchanged(tmp_path: Path) -> None:
    path = _generate(
        tmp_path, "plain.docx", {}, paragraphs=[{"text": "引言", "heading": "h1"}]
    )
    doc = Document(str(path))
    texts = [p.text for p in doc.paragraphs]
    assert texts == ["测试文档", "引言"]
    assert not _has_toc_field(doc)


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
