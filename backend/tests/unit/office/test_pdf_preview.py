"""Unit tests for backend.office.pdf_preview (Round A P1 高保真预览).

``export_to_pdf`` 被 monkeypatch 成假转换器（在指定位置写出假 PDF），
测试聚焦 pdf_preview 自己的职责：路径校验、缓存命中/失效、逐出、
data URL 生成与大小上限。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from backend.office import pdf_preview
from backend.office.export_pdf import ExportPdfResult
from backend.office.pdf_preview import PREVIEW_CACHE_DIRNAME, render_pdf_preview


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def _make_source(workspace: Path, name: str = "report.docx") -> Path:
    source = workspace / name
    source.write_bytes(b"PK\x03\x04 fake office document")
    return source


def _fake_converter(monkeypatch, calls, *, ok=True, payload=b"%PDF-1.4 fake"):
    """假 export_to_pdf：在 tmp source 旁写出 <stem>.pdf 并计数调用。"""

    def fake(source: Path, workspace: Path, **kwargs):
        calls.append(source)
        if not ok:
            return ExportPdfResult(ok=False, error="没有可用的本机转换器（soffice 未安装）")
        out = source.with_suffix(".pdf")
        out.write_bytes(payload)
        return ExportPdfResult(ok=True, method="libreoffice", output_path=str(out))

    monkeypatch.setattr(pdf_preview, "export_to_pdf", fake)


def test_success_produces_data_url_and_cache(ws, monkeypatch):
    calls = []
    _fake_converter(monkeypatch, calls)
    source = _make_source(ws)

    result = render_pdf_preview(source, ws)
    assert result.ok is True
    assert result.cached is False
    assert result.data_url is not None
    assert result.data_url.startswith("data:application/pdf;base64,")
    # 缓存目录里应有一份 <key>.pdf
    cache_dir = ws / PREVIEW_CACHE_DIRNAME
    assert len(list(cache_dir.glob("*.pdf"))) == 1
    assert len(calls) == 1


def test_cache_hit_skips_converter(ws, monkeypatch):
    calls = []
    _fake_converter(monkeypatch, calls)
    source = _make_source(ws)

    first = render_pdf_preview(source, ws)
    second = render_pdf_preview(source, ws)
    assert first.cached is False
    assert second.ok is True
    assert second.cached is True
    assert len(calls) == 1  # 第二次未触发转换


def test_source_change_invalidates_cache(ws, monkeypatch):
    calls = []
    _fake_converter(monkeypatch, calls)
    source = _make_source(ws)

    render_pdf_preview(source, ws)
    # 修改源文件（内容 + mtime）→ key 变化 → 重新转换
    source.write_bytes(b"PK\x03\x04 CHANGED office document!")
    os.utime(source, (time.time() + 5, time.time() + 5))
    result = render_pdf_preview(source, ws)
    assert result.ok is True
    assert result.cached is False
    assert len(calls) == 2


def test_converter_failure_folds_to_ok_false(ws, monkeypatch):
    calls = []
    _fake_converter(monkeypatch, calls, ok=False)
    source = _make_source(ws)

    result = render_pdf_preview(source, ws)
    assert result.ok is False
    assert result.error is not None
    assert "soffice" in result.error


def test_unsupported_extension_rejected(ws):
    bad = ws / "notes.txt"
    bad.write_text("hello")
    result = render_pdf_preview(bad, ws)
    assert result.ok is False
    assert "不支持" in (result.error or "")


def test_workspace_escape_rejected(ws, tmp_path):
    outside = tmp_path / "outside.docx"
    outside.write_bytes(b"PK\x03\x04")
    result = render_pdf_preview(outside, ws)
    assert result.ok is False


def test_oversized_pdf_rejected(ws, monkeypatch):
    calls = []
    _fake_converter(monkeypatch, calls)
    monkeypatch.setattr(pdf_preview, "_MAX_PREVIEW_PDF_BYTES", 4)
    source = _make_source(ws)
    result = render_pdf_preview(source, ws)
    assert result.ok is False
    assert "20MB" in (result.error or "") or "上限" in (result.error or "")


def test_eviction_keeps_cache_bounded(ws, monkeypatch):
    calls = []
    _fake_converter(monkeypatch, calls)
    monkeypatch.setattr(pdf_preview, "_CACHE_MAX_FILES", 2)
    for i in range(4):
        render_pdf_preview(_make_source(ws, f"doc{i}.docx"), ws)
    cache_dir = ws / PREVIEW_CACHE_DIRNAME
    assert len(list(cache_dir.glob("*.pdf"))) <= 2


def test_never_raises_on_internal_crash(ws, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("converter exploded")

    monkeypatch.setattr(pdf_preview, "export_to_pdf", boom)
    source = _make_source(ws)
    result = render_pdf_preview(source, ws)
    assert result.ok is False
    assert "内部错误" in (result.error or "")
