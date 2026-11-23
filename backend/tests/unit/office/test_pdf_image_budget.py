# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""M6c：PDF 内嵌图片提取的**有界性**测试。

覆盖两个审查代理判 BLOCK 的根因：

- 预算必须在**解码前**判定（用户可控 PDF 里的 Flate 位图 = 解压炸弹）；
- 预算必须真的约束住返回体（原来只查 raw 字节，且工具面还会二次截断）。

逐条对应：

- ``_image_precheck_ok``：像素/字节预检在 ``Pixmap`` 分配之前拦截；
- ``read_pdf``：``max_images_per_page`` 服务端 clamp；
- 全文档 base64 总量预算；
- ``embed_image_data=False``：完全不解码（零炸弹风险）；
- 灰度 / alpha 图统一转成 JPEG 预览并按最长边缩放。
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from backend.office.pdf import (
    MAX_EMBEDDED_IMAGE_EDGE,
    MAX_EMBEDDED_IMAGE_PIXELS,
    MAX_IMAGES_PER_PAGE,
    MAX_TOTAL_EMBEDDED_IMAGE_BYTES,
    _image_precheck_ok,
    read_pdf,
)

pytestmark = pytest.mark.unit

pymupdf = pytest.importorskip("pymupdf")


# ── Helpers ───────────────────────────────────────────────────────────


def _pdf_with_images(
    tmp_path: Path,
    count: int = 1,
    size: int = 20,
    mode: str = "RGB",
    name: str = "with-images.pdf",
) -> Path:
    """生成一页含 ``count`` 张**互不相同**图片的 PDF（不同颜色 → 不同 xref）。"""
    from PIL import Image

    path = tmp_path / name
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=600, height=400)
        for index in range(count):
            buffer = io.BytesIO()
            color = (
                (index * 37) % 256,
                (index * 91) % 256,
                (index * 143) % 256,
            )
            if mode == "L":
                # 灰度图只接受标量颜色。
                color = (index * 37) % 256
            Image.new(mode, (size, size), color).save(buffer, format="PNG")
            left = 10 + (index % 10) * 30
            top = 10 + (index // 10) * 30
            page.insert_image(
                pymupdf.Rect(left, top, left + 25, top + 25),
                stream=buffer.getvalue(),
            )
        doc.save(str(path))
    finally:
        doc.close()
    return path


# ── 解码前预检 ────────────────────────────────────────────────────────


def test_image_precheck_accepts_ordinary_image():
    assert _image_precheck_ok(1, 100, 100, 8, "DeviceRGB") is True


def test_image_precheck_rejects_oversized_pixels():
    """16000×16000 的图 → 解码前就被拒（250MB+ 位图，压缩后可能只有几十 KB）。"""
    assert _image_precheck_ok(1, 16000, 16000, 8, "DeviceRGB") is False


def test_image_precheck_rejects_oversized_decoded_bytes():
    """像素数达标但每像素字节数高（16bpc CMYK）→ 按解码字节数拒。"""
    assert _image_precheck_ok(1, 4000, 3000, 16, "DeviceCMYK") is False


def test_image_precheck_rejects_unknown_dimensions():
    assert _image_precheck_ok(1, 0, 100, 8, "DeviceRGB") is False


def test_oversized_image_is_skipped_but_read_still_succeeds(
    tmp_path: Path, monkeypatch
):
    """预算内的图跳过 → 该图不返回，但整份 PDF 仍然读得出来。"""
    monkeypatch.setattr("backend.office.pdf.MAX_EMBEDDED_IMAGE_PIXELS", 1)
    path = _pdf_with_images(tmp_path, count=1)

    result = read_pdf(path, workspace_path=str(tmp_path), include_images=True)

    assert result.pages[0].images == []
    assert result.pages[0].image_count == 1


# ── max_images_per_page 服务端 clamp ──────────────────────────────────


def test_max_images_per_page_is_clamped_to_hard_limit(tmp_path: Path):
    """调用方给 999 → 服务端 clamp 到 MAX_IMAGES_PER_PAGE。"""
    path = _pdf_with_images(tmp_path, count=MAX_IMAGES_PER_PAGE + 2)

    result = read_pdf(
        path,
        workspace_path=str(tmp_path),
        include_images=True,
        max_images_per_page=999,
    )

    assert len(result.pages[0].images) == MAX_IMAGES_PER_PAGE


def test_negative_max_images_per_page_yields_no_images(tmp_path: Path):
    path = _pdf_with_images(tmp_path, count=2)

    result = read_pdf(
        path,
        workspace_path=str(tmp_path),
        include_images=True,
        max_images_per_page=-5,
    )

    assert result.pages[0].images == []
    assert result.pages[0].image_count == 2


def test_non_numeric_max_images_per_page_is_treated_as_zero(tmp_path: Path):
    path = _pdf_with_images(tmp_path, count=1)

    result = read_pdf(
        path,
        workspace_path=str(tmp_path),
        include_images=True,
        max_images_per_page="abc",  # type: ignore[arg-type]
    )

    assert result.pages[0].images == []


def test_image_count_may_exceed_returned_images(tmp_path: Path):
    """image_count 是页内图片**总数**，images 受 per-page 上限截断。"""
    path = _pdf_with_images(tmp_path, count=3)

    result = read_pdf(
        path,
        workspace_path=str(tmp_path),
        include_images=True,
        max_images_per_page=1,
    )

    assert result.pages[0].image_count == 3
    assert len(result.pages[0].images) == 1


# ── 全文档预算 ────────────────────────────────────────────────────────


def test_total_budget_caps_returned_images(tmp_path: Path, monkeypatch):
    """把全文档预算压到极小 → 一张都放不下（预算按 base64 编码后计）。"""
    monkeypatch.setattr("backend.office.pdf.MAX_TOTAL_EMBEDDED_IMAGE_BYTES", 64)
    path = _pdf_with_images(tmp_path, count=2)

    result = read_pdf(path, workspace_path=str(tmp_path), include_images=True)

    assert result.pages[0].images == []
    assert result.pages[0].image_count == 2


def test_default_total_budget_is_bounded():
    assert 0 < MAX_TOTAL_EMBEDDED_IMAGE_BYTES <= 20 * 1024 * 1024


# ── metadata-only 模式 ────────────────────────────────────────────────


def test_embed_image_data_false_returns_metadata_only(tmp_path: Path):
    path = _pdf_with_images(tmp_path, count=1)

    result = read_pdf(
        path,
        workspace_path=str(tmp_path),
        include_images=True,
        embed_image_data=False,
    )

    entry = result.pages[0].images[0]
    assert "data_url" not in entry
    assert entry["width"] == 20
    assert entry["height"] == 20


def test_metadata_only_mode_never_decodes(tmp_path: Path, monkeypatch):
    """metadata-only 完全不碰 Pixmap —— 解压炸弹无从触发。"""

    def _boom(*_args, **_kwargs):
        raise AssertionError("metadata-only 模式不应解码任何位图")

    monkeypatch.setattr(pymupdf, "Pixmap", _boom)

    path = _pdf_with_images(tmp_path, count=1)
    result = read_pdf(
        path,
        workspace_path=str(tmp_path),
        include_images=True,
        embed_image_data=False,
    )

    assert len(result.pages[0].images) == 1


# ── 预览归一化（统一 JPEG + 缩放）────────────────────────────────────


def test_grayscale_image_is_converted_to_jpeg(tmp_path: Path):
    path = _pdf_with_images(tmp_path, count=1, mode="L")

    result = read_pdf(path, workspace_path=str(tmp_path), include_images=True)

    assert result.pages[0].images[0]["data_url"].startswith("data:image/jpeg")


def test_alpha_image_is_converted_to_jpeg(tmp_path: Path):
    path = _pdf_with_images(tmp_path, count=1, mode="RGBA")

    result = read_pdf(path, workspace_path=str(tmp_path), include_images=True)

    assert result.pages[0].images[0]["data_url"].startswith("data:image/jpeg")


def test_large_image_is_downscaled_to_preview_edge(tmp_path: Path):
    """2000×2000 的图 → 预览最长边 ≤ MAX_EMBEDDED_IMAGE_EDGE。"""
    path = _pdf_with_images(tmp_path, count=1, size=2000)

    result = read_pdf(path, workspace_path=str(tmp_path), include_images=True)

    entry = result.pages[0].images[0]
    assert max(entry["width"], entry["height"]) <= MAX_EMBEDDED_IMAGE_EDGE


def test_preview_edge_constant_is_sane():
    assert 0 < MAX_EMBEDDED_IMAGE_EDGE <= 2048
    assert 0 < MAX_EMBEDDED_IMAGE_PIXELS <= 100_000_000
