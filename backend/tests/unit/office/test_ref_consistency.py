"""Unit tests for Round 63 — 脚注/尾注引用一致性 lint。"""

from __future__ import annotations

import base64

import pytest
from docx import Document
from docx.oxml.ns import qn

from backend.office.models import (
    OfficeWordGenerateRequest,
    WordFormatSpec,
    WordImageSpec,
    WordParagraphSpec,
    WordTableSpec,
)
from backend.office.word import generate_docx
from backend.office.word_lint import lint_docx

pytestmark = pytest.mark.unit

_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _gen_with_footnote(tmp_path, name):
    image_file = tmp_path / "tiny.png"
    image_file.write_bytes(base64.b64decode(_TINY_PNG_B64))
    req = OfficeWordGenerateRequest(
        workspace_path="",
        filename=name,
        title="报告",
        paragraphs=[WordParagraphSpec(text="正文{{fn:备注}}。")],
        images=[WordImageSpec(source=str(image_file), caption="架构图")],
        tables=[WordTableSpec(headers=["A"], rows=[["1"]])],
    )
    return generate_docx(req, output_dir=str(tmp_path))


def test_consistent_footnote_refs_pass(tmp_path) -> None:
    path = _gen_with_footnote(tmp_path, "ok.docx")
    result = lint_docx(path, WordFormatSpec())
    broken = [i for i in result.issues if "broken_ref" in i.rule_id]
    assert broken == []
    assert "ref_consistency" in result.checked_rules


def test_broken_footnote_ref_detected(tmp_path) -> None:
    """引用 id=2 但 part 无对应 note → footnote/broken_ref error。"""
    path = _gen_with_footnote(tmp_path, "broken.docx")
    doc = Document(str(path))
    for p in doc.paragraphs:
        for el in p._p.findall(".//" + qn("w:footnoteReference")):
            el.set(qn("w:id"), "2")  # 指向不存在的 note
    doc.save(str(path))

    result = lint_docx(path, WordFormatSpec())
    broken = [i for i in result.issues if i.rule_id == "footnote/broken_ref"]
    assert len(broken) == 1
    assert broken[0].severity == "error"


def test_docs_without_refs_skip_consistency(tmp_path) -> None:
    """无脚注/尾注引用的文档 → ref_consistency 不入 checked。"""
    doc = Document()
    doc.add_paragraph("无引用正文")
    path = tmp_path / "plain.docx"
    doc.save(str(path))
    result = lint_docx(path, WordFormatSpec())
    # 无引用文档：规则无条件启用但零开销跳过
    assert "ref_consistency" in result.checked_rules
    assert result.ok is True
