"""Unit tests for backend.office.template_thumbnail (Round C P5).

export_to_pdf 与 fitz 均可能不在测试环境 —— 转换器 monkeypatch 成假
实现（写出一页真 PDF 由 reportlab 生成太重，这里直接用 fitz 的最小
PDF；fitz 缺失时跳过光栅化用例）。缓存/逐出/失败折叠逻辑不依赖二者。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.office import template_thumbnail
from backend.office.export_pdf import ExportPdfResult
from backend.office.template_thumbnail import (
    THUMB_CACHE_DIRNAME,
    render_template_thumbnail,
)

fitz = pytest.importorskip("fitz", reason="PyMuPDF required for thumbnail tests")


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def _make_template(tmp_path: Path, name: str = "tpl.docx") -> Path:
    source = tmp_path / name
    source.write_bytes(b"PK\x03\x04 fake docx template")
    return source


def _minimal_pdf_bytes() -> bytes:
    """One blank A4 page via fitz itself."""
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    data = doc.tobytes()
    doc.close()
    return data


def _fake_converter(monkeypatch, calls, *, ok=True):
    pdf_bytes = _minimal_pdf_bytes()

    def fake(source: Path, workspace: Path, **kwargs):
        calls.append(source)
        if not ok:
            return ExportPdfResult(ok=False, error="没有可用的本机转换器（soffice 未安装）")
        out = source.with_suffix(".pdf")
        out.write_bytes(pdf_bytes)
        return ExportPdfResult(ok=True, method="libreoffice", output_path=str(out))

    monkeypatch.setattr(template_thumbnail, "export_to_pdf", fake)


def test_success_produces_png_data_url_and_cache(ws, tmp_path, monkeypatch):
    calls = []
    _fake_converter(monkeypatch, calls)
    source = _make_template(tmp_path)

    result = render_template_thumbnail(source, ws, cache_key="builtin:tpl")
    assert result.ok is True
    assert result.cached is False
    assert result.data_url is not None
    assert result.data_url.startswith("data:image/png;base64,")
    assert len(list((ws / THUMB_CACHE_DIRNAME).glob("*.png"))) == 1


def test_cache_hit_skips_conversion(ws, tmp_path, monkeypatch):
    calls = []
    _fake_converter(monkeypatch, calls)
    source = _make_template(tmp_path)

    render_template_thumbnail(source, ws, cache_key="builtin:tpl")
    second = render_template_thumbnail(source, ws, cache_key="builtin:tpl")
    assert second.ok is True
    assert second.cached is True
    assert len(calls) == 1


def test_converter_failure_folds_to_ok_false(ws, tmp_path, monkeypatch):
    calls = []
    _fake_converter(monkeypatch, calls, ok=False)
    source = _make_template(tmp_path)

    result = render_template_thumbnail(source, ws, cache_key="builtin:tpl")
    assert result.ok is False
    assert "soffice" in (result.error or "")


def test_missing_source_folds_to_ok_false(ws, tmp_path):
    result = render_template_thumbnail(
        tmp_path / "ghost.docx", ws, cache_key="builtin:ghost"
    )
    assert result.ok is False
    assert "不存在" in (result.error or "")


def test_eviction_bounds_cache(ws, tmp_path, monkeypatch):
    calls = []
    _fake_converter(monkeypatch, calls)
    monkeypatch.setattr(template_thumbnail, "_CACHE_MAX_FILES", 2)
    for i in range(4):
        source = _make_template(tmp_path, f"tpl{i}.docx")
        render_template_thumbnail(source, ws, cache_key=f"builtin:tpl{i}")
    assert len(list((ws / THUMB_CACHE_DIRNAME).glob("*.png"))) <= 2


def test_never_raises_on_crash(ws, tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("converter exploded")

    monkeypatch.setattr(template_thumbnail, "export_to_pdf", boom)
    result = render_template_thumbnail(
        _make_template(tmp_path), ws, cache_key="builtin:tpl"
    )
    assert result.ok is False
    assert "内部错误" in (result.error or "")
