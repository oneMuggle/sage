"""CJK output tests for :func:`backend.office.pdf.generate_pdf` (Item 1.3).

generate_pdf 之前只用 base-14 Helvetica（无 CJK 字形），中文渲染为空白。
修复后注册 STSong-Light（reportlab 自带的 Adobe CID 字体，同时覆盖 ASCII），
生成的 PDF 可用 PyMuPDF 把中文原样提取回来，中英文混排不受影响。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.office.models import PdfGenerateRequest, PdfPageSpec

pytestmark = pytest.mark.unit


def _generate_mixed_pdf(tmp_path: Path) -> Path:
    """Generate a PDF with mixed Chinese/English title, paragraphs and table."""
    from backend.office.pdf import generate_pdf

    req = PdfGenerateRequest(
        workspace_path=str(tmp_path),
        filename="cjk.pdf",
        pages=[
            PdfPageSpec(
                title="季度报告 Quarterly Report",
                paragraphs=["这是中文段落。", "Mixed 中英文 paragraph."],
                tables=[[["姓名", "Score"], ["张三", "90"]]],
            )
        ],
    )
    result = generate_pdf(req)
    return Path(result.output_path)


def test_generate_pdf_cjk_title_and_paragraphs(tmp_path: Path) -> None:
    """Chinese title + paragraph text extracts back from the generated PDF."""
    import pymupdf

    path = _generate_mixed_pdf(tmp_path)

    doc = pymupdf.open(str(path))
    try:
        text = doc[0].get_text()
    finally:
        doc.close()

    assert "季度报告" in text
    assert "Quarterly Report" in text
    assert "这是中文段落" in text
    assert "Mixed" in text
    assert "中英文" in text
    assert "paragraph" in text


def test_generate_pdf_cjk_table_cells(tmp_path: Path) -> None:
    """Table stub rows also render CJK cell text."""
    import pymupdf

    path = _generate_mixed_pdf(tmp_path)

    doc = pymupdf.open(str(path))
    try:
        text = doc[0].get_text()
    finally:
        doc.close()

    assert "姓名" in text
    assert "张三" in text
    assert "Score" in text


def test_generate_pdf_cjk_font_embedded(tmp_path: Path) -> None:
    """The page fonts include the registered CID font (STSong-Light)."""
    import pymupdf

    path = _generate_mixed_pdf(tmp_path)

    doc = pymupdf.open(str(path))
    try:
        fonts = doc[0].get_fonts()
    finally:
        doc.close()

    font_names = " ".join(str(f[3]) for f in fonts)
    assert "STSong-Light" in font_names


def test_generate_pdf_falls_back_when_font_registration_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Registration failure must degrade to Helvetica, not break generation."""
    from reportlab.pdfbase import cidfonts

    def _boom(*args, **kwargs):
        raise RuntimeError("no asian font pack")

    # 只让 UnicodeCIDFont 构造失败；不能 patch pdfmetrics.registerFont ——
    # base-14 Helvetica 的懒加载也走它，会把回退路径一起炸掉。
    monkeypatch.setattr(cidfonts, "UnicodeCIDFont", _boom)

    from backend.office.pdf import generate_pdf

    req = PdfGenerateRequest(
        workspace_path=str(tmp_path),
        filename="latin.pdf",
        pages=[PdfPageSpec(title="Fallback", paragraphs=["plain latin"])],
    )
    result = generate_pdf(req)

    import pymupdf

    doc = pymupdf.open(result.output_path)
    try:
        text = doc[0].get_text()
    finally:
        doc.close()
    assert "Fallback" in text
    assert "plain latin" in text
