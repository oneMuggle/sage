"""P2-A (office-p2a)：HTML→PDF 生成路线测试。

soffice 打桩（fake subprocess.run 用 PyMuPDF 产出真实 PDF）；
reportlab 回落路径靠「soffice 缺失」注入验证。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from backend.office import pdf_html
from backend.office.models import PdfGenerateRequest, PdfPageSpec
from backend.office.pdf import generate_pdf
from backend.office.pdf_html import generate_pdf_via_soffice, render_pages_html

pytestmark = pytest.mark.unit


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def _req(ws: Path, **overrides: Any) -> PdfGenerateRequest:
    payload: dict = {
        "workspace_path": str(ws),
        "filename": "out.pdf",
        "pages": [
            PdfPageSpec(
                title="第一章",
                paragraphs=["中文长段落，需要自动换行。" * 10, "含 <script>alert(1)</script> 的文本"],
                tables=[[["名称", "值"], ["苹果", "3"]]],
            ),
            PdfPageSpec(title="第二章", paragraphs=["第二页正文"], tables=[]),
        ],
    }
    payload.update(overrides)
    return PdfGenerateRequest(**payload)


def _fake_soffice(monkeypatch: pytest.MonkeyPatch, ws: Path, *, ok: bool = True) -> None:
    """Pin soffice 定位 + fake run：在 outdir 产出真实 PDF（PyMuPDF 生成）。"""

    def fake_run(cmd: list, **kwargs: Any) -> subprocess.CompletedProcess:
        outdir = Path(cmd[cmd.index("--outdir") + 1])
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "html route output")
        doc.save(str(outdir / "doc.pdf"))
        doc.close()
        return subprocess.CompletedProcess(cmd, 0 if ok else 2, stdout=b"", stderr=b"nope")

    monkeypatch.setattr(pdf_html, "_locate_soffice", lambda: "/fake/soffice")
    monkeypatch.setattr(pdf_html.subprocess, "run", fake_run)


class TestRenderPagesHtml:
    def test_escapes_user_text(self, ws: Path) -> None:
        html_doc = render_pages_html(_req(ws))
        assert "<script>" not in html_doc
        assert "&lt;script&gt;" in html_doc

    def test_renders_tables_and_titles(self, ws: Path) -> None:
        html_doc = render_pages_html(_req(ws))
        assert "<h1>第一章</h1>" in html_doc
        assert html_doc.count("<table>") == 1
        assert "<td>苹果</td>" in html_doc

    def test_page_size_css(self, ws: Path) -> None:
        html_doc = render_pages_html(_req(ws, page_size="Legal"))
        assert "8.5in 14in" in html_doc


class TestSofficeRoute:
    def test_generates_real_pdf(self, ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _fake_soffice(monkeypatch, ws)
        out = ws / "out.pdf"
        assert generate_pdf_via_soffice(_req(ws), out) is True
        doc = pymupdf.open(str(out))
        assert doc.page_count >= 1
        doc.close()

    def test_missing_soffice_returns_false(self, ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pdf_html, "_locate_soffice", lambda: None)
        assert generate_pdf_via_soffice(_req(ws), ws / "out.pdf") is False

    def test_converter_failure_returns_false(self, ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _fake_soffice(monkeypatch, ws, ok=False)
        assert generate_pdf_via_soffice(_req(ws), ws / "out.pdf") is False

    def test_refuses_existing_output(self, ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _fake_soffice(monkeypatch, ws)
        out = ws / "out.pdf"
        out.write_bytes(b"existing")
        assert generate_pdf_via_soffice(_req(ws), out) is False
        assert out.read_bytes() == b"existing"  # 未覆盖


class TestGeneratePdfDispatch:
    def test_uses_html_route_when_soffice_available(
        self, ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_soffice(monkeypatch, ws)
        result = generate_pdf(_req(ws))
        assert result.page_count == 2
        doc = pymupdf.open(result.output_path)
        assert "html route output" in doc[0].get_text()
        doc.close()

    def test_falls_back_to_reportlab_without_soffice(
        self, ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pdf_html, "_locate_soffice", lambda: None)
        result = generate_pdf(_req(ws))
        assert result.page_count == 2
        doc = pymupdf.open(result.output_path)
        text = "".join(p.get_text() for p in doc)
        assert "第一章" in text
        doc.close()
