"""P4-A (office-p4a)：扫描页 OCR 兜底测试。

pytesseract 通过 fake 模块注入（sys.modules），tesseract 用
shutil.which 打桩；核心语义：有文本层不 OCR / 未开启不 OCR /
依赖缺失不 OCR / 全条件满足产出识别文本并标记 ocr=True。
"""

from __future__ import annotations

import sys
import types

import pytest

pytestmark = pytest.mark.unit


class _FakePage:
    """最小 pymupdf 页桩：get_pixmap 返回带 tobytes 的像素对象。"""

    def get_pixmap(self, dpi: int = 72):
        class _Pix:
            def tobytes(self, fmt: str) -> bytes:
                assert fmt == "png"
                return b"fake-png"

        return _Pix()


def _install_fake_deps(monkeypatch: pytest.MonkeyPatch, recognized: str) -> None:
    """注入 fake pytesseract + PIL + tesseract PATH。"""
    pytesseract_mod = types.ModuleType("pytesseract")

    def image_to_string(img, lang=None):  # noqa: ANN001
        assert lang == "eng+chi_sim"
        return recognized

    pytesseract_mod.image_to_string = image_to_string
    monkeypatch.setitem(sys.modules, "pytesseract", pytesseract_mod)

    pil_mod = types.ModuleType("PIL")
    import importlib.util as _ilu

    pil_mod.__spec__ = _ilu.spec_from_loader("PIL", loader=None)
    image_mod = types.ModuleType("PIL.Image")

    class _FakeImage:
        @staticmethod
        def open(data):  # noqa: ANN001
            return object()

    image_mod.Image = _FakeImage
    pil_mod.Image = image_mod.Image
    monkeypatch.setitem(sys.modules, "PIL", pil_mod)
    monkeypatch.setitem(sys.modules, "PIL.Image", image_mod)
    monkeypatch.setattr("shutil.which", lambda name: r"C:\fake\tesseract.exe" if name == "tesseract" else None)


@pytest.fixture(name="ocr_enabled")
def _ocr_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAGE_OCR", "1")
    _install_fake_deps(monkeypatch, "OCR 识别文本")


def test_text_layer_present_skips_ocr(ocr_enabled) -> None:
    from backend.office.ocr import ocr_page_if_needed

    assert ocr_page_if_needed(_FakePage(), "这一页有正常文本层" * 5) is None


def test_blank_page_ocr_disabled_passes_through(monkeypatch) -> None:
    monkeypatch.delenv("SAGE_OCR", raising=False)
    from backend.office.ocr import ocr_page_if_needed

    assert ocr_page_if_needed(_FakePage(), "") is None


def test_missing_deps_passes_through(monkeypatch) -> None:
    monkeypatch.setenv("SAGE_OCR", "1")
    # 不注入 fake 依赖（sys.modules 无 pytesseract）
    monkeypatch.setattr("shutil.which", lambda name: None)
    from backend.office.ocr import ocr_page_if_needed

    assert ocr_page_if_needed(_FakePage(), "") is None


def test_blank_page_ocr_recognizes(ocr_enabled) -> None:
    from backend.office.ocr import ocr_page_if_needed

    assert ocr_page_if_needed(_FakePage(), "  ") == "OCR 识别文本"


def test_is_ocr_enabled_env(monkeypatch) -> None:
    from backend.office.ocr import is_ocr_enabled

    monkeypatch.delenv("SAGE_OCR", raising=False)
    assert is_ocr_enabled() is False
    monkeypatch.setenv("SAGE_OCR", "1")
    assert is_ocr_enabled() is True


def test_read_pdf_marks_ocr_pages(tmp_path, monkeypatch) -> None:
    """集成：无文本层 + OCR 开启 → read_pdf 页面 ocr=True 且带识别文本。"""
    import pymupdf

    from backend.office.pdf import read_pdf

    pdf_path = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((10, 15), " ")  # 1 字符 < OCR_MIN_TEXT_CHARS
    doc.save(str(pdf_path))
    doc.close()

    # fake 识别文本——这里直接打桩 ocr_page_if_needed
    monkeypatch.setattr(
        "backend.office.ocr.ocr_page_if_needed", lambda page, text: "OCR PAGE TEXT"
    )
    result = read_pdf(pdf_path, workspace_path=str(tmp_path))
    assert result.pages[0].ocr is True
    assert result.pages[0].text == "OCR PAGE TEXT"


def test_read_pdf_without_ocr_marks_false(tmp_path, monkeypatch) -> None:
    import pymupdf

    from backend.office.pdf import read_pdf

    pdf_path = tmp_path / "text.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "hello world " * 10)
    doc.save(str(pdf_path))
    doc.close()

    result = read_pdf(pdf_path, workspace_path=str(tmp_path))
    assert all(p.ocr is False for p in result.pages)


def test_capabilities_reports_ocr(monkeypatch) -> None:
    from backend.office import capabilities

    _install_fake_deps(monkeypatch, "x")
    monkeypatch.setenv("SAGE_OCR", "1")
    caps = capabilities.probe_capabilities(force=True)
    assert caps.ocr_available is True
