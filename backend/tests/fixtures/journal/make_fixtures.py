"""生成测试用 docx fixture：simple_chinese_template / bad_template_corrupt / good_filled_paper / bad_filled_paper。

运行：python -m backend.tests.fixtures.journal.make_fixtures
生成的 docx 写到 backend/tests/fixtures/journal/*.docx
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from docx import Document
from docx.shared import Cm, Pt

FIXTURE_DIR = Path(__file__).resolve().parent


def _save_simple_chinese_template() -> Path:
    """中文期刊模板：宋体小四正文 + 黑体三号标题 + 1.5 倍行距 + A4 + 2.54 边距"""
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    pf = style.paragraph_format
    pf.line_spacing = 1.5

    section = doc.sections[0]
    section.page_height = Cm(29.7)
    section.page_width = Cm(21.0)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(2.54)
    section.right_margin = Cm(2.54)

    h = doc.add_heading("摘要", level=1)
    h.style.font.name = "黑体"
    h.style.font.size = Pt(16)

    doc.add_paragraph("这是中文模板示例正文段落。")
    doc.add_heading("关键词", level=1)
    doc.add_paragraph("关键词；模板；测试")

    out = FIXTURE_DIR / "simple_chinese_template.docx"
    doc.save(str(out))
    return out


def _save_bad_template_corrupt() -> Path:
    """坏文件：合法 zip 但缺 [Content_Types].xml"""
    out = FIXTURE_DIR / "bad_template_corrupt.docx"
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("word/document.xml", "<w:document xmlns:w=\"w\"/>")
    return out


def _save_good_filled_paper() -> Path:
    """合规成稿：与 simple_chinese_template 同样字体字号行距边距"""
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    style.paragraph_format.line_spacing = 1.5
    section = doc.sections[0]
    for attr in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(section, attr, Cm(2.54))
    doc.add_heading("摘要", level=1)
    doc.add_paragraph("合规摘要内容。")
    doc.add_heading("关键词", level=1)
    doc.add_paragraph("合规；关键词")
    out = FIXTURE_DIR / "good_filled_paper.docx"
    doc.save(str(out))
    return out


def _save_bad_filled_paper() -> Path:
    """违规成稿：Calibri 11pt + 单倍行距 + 边距 1.5cm（全部不匹配）"""
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    style.paragraph_format.line_spacing = 1.0
    section = doc.sections[0]
    for attr in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(section, attr, Cm(1.5))
    doc.add_heading("Summary", level=1)
    doc.add_paragraph("Non-conforming content.")
    out = FIXTURE_DIR / "bad_filled_paper.docx"
    doc.save(str(out))
    return out


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    paths = [
        _save_simple_chinese_template(),
        _save_bad_template_corrupt(),
        _save_good_filled_paper(),
        _save_bad_filled_paper(),
    ]
    for p in paths:
        print(f"wrote {p.name} {p.stat().st_size}B")


if __name__ == "__main__":
    main()
