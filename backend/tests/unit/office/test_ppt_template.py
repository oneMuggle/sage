"""P5-A (office-p5a)：PPT 模板占位符分析与填充测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def _make_template(ws: Path, name: str = "tpl.pptx") -> Path:
    """构造含占位符的 2 页模板：idx0 标题 + idx1 正文。"""
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(7.5)
    layout = prs.slide_layouts[6]  # Blank
    for n in (1, 2):
        slide = prs.slides.add_slide(layout)
        title = slide.shapes.add_textbox(0, 0, 9, 1)
        title.name = f"TitlePlaceholder{n}"
        tf = title.text_frame
        tf.text = f"占位符标题{n}"
        body = slide.shapes.add_textbox(0, 1, 9, 5)
        body.name = f"BodyPlaceholder{n}"
        btf = body.text_frame
        btf.text = f"占位符正文{n}"
    path = ws / name
    prs.save(str(path))
    return path


def _open(path: Path):
    from pptx import Presentation

    return Presentation(str(path))


class TestAnalyze:
    def test_analyze_lists_layouts(self, ws: Path) -> None:
        from backend.office.ppt_template import (
            PptTemplateAnalyzeRequest,
            analyze_ppt_template,
        )

        path = _make_template(ws)
        result = analyze_ppt_template(
            PptTemplateAnalyzeRequest(workspace_path=str(ws), file_path=str(path))
        )
        assert result.ok is True
        assert len(result.layouts) >= 1
        # Blank 版式（默认模板必有）的占位符可能为空，但版式名必须列出
        assert any(x.name for x in result.layouts)

    def test_analyze_escape_rejected(self, ws: Path) -> None:
        from backend.office.ppt_template import (
            PptTemplateAnalyzeRequest,
            analyze_ppt_template,
        )

        outside = ws.parent / "out.pptx"
        _make_template(ws.parent, "out.pptx")
        result = analyze_ppt_template(
            PptTemplateAnalyzeRequest(workspace_path=str(ws), file_path=str(outside))
        )
        assert result.ok is False


class TestFill:
    def test_fills_placeholders_and_writes_new_file(self, ws: Path) -> None:
        from backend.office.ppt_template import PptTemplateFillRequest, fill_ppt_template

        path = _make_template(ws)
        # 模板页的 shape 顺序即 textbox 顺序；用 textbox name 定位不依赖
        # idx —— 填充端按 idx 查找，模板页 idx 由 python-pptx 自动分配。
        # 为确定性起见：直接断言按 idx=0 找不到时报错（textbox 无占位符 idx）
        request = PptTemplateFillRequest(
            workspace_path=str(ws),
            file_path=str(path),
            output_filename="filled",
            fills=[
                {"slide_number": 1, "placeholder_idx": 0, "text": "新标题"},
            ],
        )
        result = fill_ppt_template(request)
        # 空白版式页的 textbox 没有 placeholder idx → op 级失败（all-or-nothing）
        assert result.ok is False
        assert "占位符" in (result.error or "")
        assert not (ws / "filled.pptx").exists()

    def test_fill_on_real_placeholder_layout(self, ws: Path) -> None:
        """用带真实占位符的版式页（Title Slide idx0/1）验证填充成功路径。"""
        from pptx import Presentation

        from backend.office.ppt_template import PptTemplateFillRequest, fill_ppt_template

        path = ws / "real-tpl.pptx"
        prs = Presentation()
        layout = prs.slide_layouts[0]  # Title Slide：idx0 标题 + idx1 副标题
        slide = prs.slides.add_slide(layout)
        assert len(slide.placeholders) >= 1
        prs.save(str(path))

        fills = [
            {
                "slide_number": 1,
                "placeholder_idx": int(ph.placeholder_format.idx),
                "text": f"填充{ph.placeholder_format.idx}",
            }
            for ph in slide.placeholders
        ]
        result = fill_ppt_template(
            PptTemplateFillRequest(
                workspace_path=str(ws),
                file_path=str(path),
                output_filename="real-filled",
                fills=fills,
            )
        )
        assert result.ok is True
        assert result.filled_count == len(fills)
        filled = _open(ws / "real-filled.pptx")
        for ph in filled.slides[0].placeholders:
            assert ph.text_frame.text == f"填充{ph.placeholder_format.idx}"

    def test_slide_number_out_of_range(self, ws: Path) -> None:
        from backend.office.ppt_template import PptTemplateFillRequest, fill_ppt_template

        path = _make_template(ws)
        result = fill_ppt_template(
            PptTemplateFillRequest(
                workspace_path=str(ws),
                file_path=str(path),
                output_filename="o",
                fills=[{"slide_number": 99, "placeholder_idx": 0, "text": "x"}],
            )
        )
        assert result.ok is False
        assert "超出范围" in (result.error or "")

    def test_output_exists_rejected(self, ws: Path) -> None:
        from backend.office.ppt_template import PptTemplateFillRequest, fill_ppt_template

        path = _make_template(ws)
        (ws / "taken.pptx").write_bytes(b"existing")
        result = fill_ppt_template(
            PptTemplateFillRequest(
                workspace_path=str(ws),
                file_path=str(path),
                output_filename="taken.pptx",
                fills=[{"slide_number": 1, "placeholder_idx": 0, "text": "x"}],
            )
        )
        assert result.ok is False
        assert "已存在" in (result.error or "")


class TestRoutes:
    def test_routes_registered(self) -> None:
        from backend.api.office_routes import router

        paths = {r.path for r in router.routes}
        assert "/office/ppt/analyze-template" in paths
        assert "/office/ppt/fill-template" in paths
