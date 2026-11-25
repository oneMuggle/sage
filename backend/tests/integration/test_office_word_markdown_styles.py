"""Integration tests for Markdown → named styles (M2 markdown upgrade).

Covers:

1. inline runs — ``**bold**`` → ``Strong`` character style, ``*italic*`` →
   ``Emphasis``, both → ``Strong`` + direct italic;
2. links — ``[text](url)`` → ``w:hyperlink`` with an external relationship
   and the ``Hyperlink`` character style; unsafe schemes stay plain text;
3. quotes — ``> ...`` → the built-in ``Quote`` paragraph style;
4. list paragraphs keep ``List Bullet`` / ``List Number`` while carrying
   inline runs;
5. legacy paragraphs (no ``runs``) remain byte-for-byte unchanged.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from backend.office.markdown_to_paragraphs import parse_markdown_document
from backend.office.models import OfficeWordGenerateRequest
from backend.office.word import generate_docx


def _generate(tmp_path: Path, **kwargs) -> Path:
    req = OfficeWordGenerateRequest(
        workspace_path="",
        filename="styles.docx",
        title="测试文档",
        **kwargs,
    )
    return generate_docx(req, output_dir=str(tmp_path))


def _find_paragraph(doc: Document, text: str):
    for paragraph in doc.paragraphs:
        if paragraph.text == text:
            return paragraph
    raise AssertionError(f"paragraph {text!r} not found in {[p.text for p in doc.paragraphs]!r}")


def _run_style_ids(paragraph) -> list:
    ids = []
    for run in paragraph._p.findall(qn("w:r")):
        rPr = run.find(qn("w:rPr"))
        style_el = rPr.find(qn("w:rStyle")) if rPr is not None else None
        ids.append(style_el.get(qn("w:val")) if style_el is not None else None)
    return ids


def _run_has(paragraph, index: int, tag: str) -> bool:
    runs = paragraph._p.findall(qn("w:r"))
    rPr = runs[index].find(qn("w:rPr"))
    return rPr is not None and rPr.find(qn(tag)) is not None


# ──────────────────────────────────────────────────────────────────────
# Inline character styles
# ──────────────────────────────────────────────────────────────────────


def test_bold_run_uses_strong_style(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        paragraphs=[
            {
                "text": "这是 加粗 文字",
                "runs": [
                    {"text": "这是 "},
                    {"text": "加粗", "bold": True},
                    {"text": " 文字"},
                ],
            }
        ],
    )
    paragraph = _find_paragraph(Document(str(path)), "这是 加粗 文字")
    assert _run_style_ids(paragraph) == [None, "Strong", None]


def test_italic_run_uses_emphasis_style(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        paragraphs=[
            {
                "text": "强调内容",
                "runs": [{"text": "强调", "italic": True}, {"text": "内容"}],
            }
        ],
    )
    paragraph = _find_paragraph(Document(str(path)), "强调内容")
    assert _run_style_ids(paragraph) == ["Emphasis", None]


def test_bold_italic_run_combines_style_and_direct(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        paragraphs=[
            {
                "text": "重点",
                "runs": [{"text": "重点", "bold": True, "italic": True}],
            }
        ],
    )
    paragraph = _find_paragraph(Document(str(path)), "重点")
    assert _run_style_ids(paragraph) == ["Strong"]
    assert _run_has(paragraph, 0, "w:i")


# ──────────────────────────────────────────────────────────────────────
# Hyperlinks
# ──────────────────────────────────────────────────────────────────────


def test_link_writes_hyperlink_relationship(tmp_path: Path) -> None:
    url = "https://example.com/doc"
    path = _generate(
        tmp_path,
        paragraphs=[
            {"text": "见 文档", "runs": [{"text": "见 "}, {"text": "文档", "link": url}]},
        ],
    )
    doc = Document(str(path))
    paragraph = _find_paragraph(doc, "见 文档")
    hyperlinks = paragraph._p.findall(qn("w:hyperlink"))
    assert len(hyperlinks) == 1
    r_id = hyperlinks[0].get(qn("r:id"))
    assert r_id
    rel = doc.part.rels[r_id]
    assert rel.is_external
    assert rel.target_ref == url
    inner_run = hyperlinks[0].find(qn("w:r"))
    rPr = inner_run.find(qn("w:rPr"))
    style_el = rPr.find(qn("w:rStyle"))
    assert style_el.get(qn("w:val")) == "Hyperlink"
    # Hyperlink 字符样式应被补建（默认模板没有）
    assert doc.styles["Hyperlink"] is not None


def test_unsafe_link_scheme_stays_plain_text(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        paragraphs=[
            {
                "text": "别点我",
                "runs": [{"text": "别点我", "link": "javascript:alert(1)"}],
            }
        ],
    )
    paragraph = _find_paragraph(Document(str(path)), "别点我")
    assert not paragraph._p.findall(qn("w:hyperlink"))


# ──────────────────────────────────────────────────────────────────────
# Quotes / lists
# ──────────────────────────────────────────────────────────────────────


def test_quote_paragraph_uses_quote_style(tmp_path: Path) -> None:
    path = _generate(tmp_path, paragraphs=[{"text": "引用文本", "style": "quote"}])
    paragraph = _find_paragraph(Document(str(path)), "引用文本")
    assert paragraph.style.name == "Quote"


def test_bullet_with_runs_keeps_list_style(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        paragraphs=[
            {
                "text": "重点内容",
                "style": "bullet",
                "runs": [{"text": "重点", "bold": True}, {"text": "内容"}],
            }
        ],
    )
    paragraph = _find_paragraph(Document(str(path)), "重点内容")
    assert paragraph.style.name == "List Bullet"
    assert _run_style_ids(paragraph) == ["Strong", None]


# ──────────────────────────────────────────────────────────────────────
# Legacy output unchanged
# ──────────────────────────────────────────────────────────────────────


def test_legacy_paragraph_has_no_run_styles(tmp_path: Path) -> None:
    path = _generate(tmp_path, paragraphs=[{"text": "普通正文"}])
    paragraph = _find_paragraph(Document(str(path)), "普通正文")
    assert _run_style_ids(paragraph) == [None]
    assert not paragraph._p.findall(qn("w:hyperlink"))


# ──────────────────────────────────────────────────────────────────────
# Markdown → generate end-to-end
# ──────────────────────────────────────────────────────────────────────


def test_markdown_document_renders_named_styles(tmp_path: Path) -> None:
    parsed = parse_markdown_document(
        "# 标题\n\n这是 **加粗** 正文\n\n> 引用警示\n\n| 列A |\n| --- |\n| 1 |"
    )
    assert parsed["tables"]
    path = _generate(
        tmp_path,
        paragraphs=parsed["paragraphs"],
        tables=parsed["tables"],
    )
    doc = Document(str(path))
    body = _find_paragraph(doc, "这是 加粗 正文")
    assert _run_style_ids(body) == [None, "Strong", None]
    quote = _find_paragraph(doc, "引用警示")
    assert quote.style.name == "Quote"
    assert doc.tables[0].cell(1, 0).text == "1"
