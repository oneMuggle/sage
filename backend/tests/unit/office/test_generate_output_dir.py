"""生成器 output_dir 参数测试：任意路径写入 + 默认行为回归。"""

from __future__ import annotations

import pytest

from backend.office.excel import generate_xlsx, read_xlsx
from backend.office.models import (
    ExcelSheetSpec,
    OfficeExcelGenerateRequest,
    OfficePptGenerateRequest,
    OfficeWordGenerateRequest,
    PptSlideSpec,
    WordParagraphSpec,
)
from backend.office.ppt import generate_ppt, read_ppt
from backend.office.word import generate_docx, read_docx

pytestmark = pytest.mark.unit


def test_generate_docx_with_output_dir(tmp_path):
    req = OfficeWordGenerateRequest(
        workspace_path="",
        filename="weather.docx",
        title="天气",
        paragraphs=[WordParagraphSpec(text="今天天气很好")],
    )
    out = generate_docx(req, output_dir=str(tmp_path))
    assert out == (tmp_path / "weather.docx")
    assert out.exists()
    result = read_docx(out, workspace_path="")
    # 标题以 Title 样式作为段落被提取，正文紧随其后（与 test_word.py 读语义一致）
    assert [p.text for p in result.paragraphs] == ["天气", "今天天气很好"]


def test_generate_xlsx_with_output_dir(tmp_path):
    req = OfficeExcelGenerateRequest(
        workspace_path="",
        filename="report.xlsx",
        sheets=[ExcelSheetSpec(name="Sheet1", headers=["A", "B"], rows=[["1", "2"]])],
    )
    out = generate_xlsx(req, output_dir=str(tmp_path))
    assert out == (tmp_path / "report.xlsx")
    assert out.exists()
    result = read_xlsx(out, workspace_path="")
    # 第 0 行是表头，第 1 行是数据行（与 test_excel.py 读语义一致）
    assert result.sheets[0].rows[1] == ["1", "2"]


def test_generate_ppt_with_output_dir(tmp_path):
    req = OfficePptGenerateRequest(
        workspace_path="",
        filename="deck.pptx",
        slides=[PptSlideSpec(title="标题", bullets=["第一点", "第二点"])],
    )
    out = generate_ppt(req, output_dir=str(tmp_path))
    assert out == (tmp_path / "deck.pptx")
    assert out.exists()
    result = read_ppt(out, workspace_path="")
    assert result.slides[0].title == "标题"


def test_generate_docx_default_output_dir_still_uses_workspace(tmp_path):
    """回归：不传 output_dir 时行为与 HTTP 端点完全一致（写 workspace 沙箱）。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    req = OfficeWordGenerateRequest(
        workspace_path=str(workspace), filename="a.docx", title="t"
    )
    out = generate_docx(req)  # output_dir=None → managed_document_path
    assert workspace in out.parents
    assert out.exists()
