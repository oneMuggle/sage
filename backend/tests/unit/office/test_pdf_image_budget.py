# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""M6c：PDF 内嵌图片提取的**有界性**与**安全性**测试。

覆盖两份复审判 BLOCK 的两个根因：

- **CRITICAL-1**：JPX（以及 JBIG2 / CCITT）这类「码流自带真实尺寸」的
  编解码器，字典里的 /Width /Height 可以随便写小 —— 预检若信了字典，
  MuPDF 会按码流真实尺寸申请位图（实测 6000×6000 → 2.1GB RSS）。
  因此这些过滤器必须在**解码前**被拒（``filter_chain_is_trusted``），
  且拒绝时**绝不能**走到 ``pymupdf.Pixmap``。
- **HIGH-2**：``include_images=False`` 时**根本不枚举**图片（``get_images``
  单页可达 0.1s），且枚举 / 解码 / 返回张数各有独立上限。

另附回归：缩放因子按 2 的幂（``Pixmap.shrink(n)`` 是除以 2**n**）、
SMask 透明度按 PDF 语义合成到白底、metadata-only 模式零解码。
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from backend.office.pdf import read_pdf
from backend.office.pdf_images import (
    MAX_EMBEDDED_IMAGE_EDGE,
    MAX_EMBEDDED_IMAGE_PIXELS,
    MAX_IMAGE_DECODES_PER_DOCUMENT,
    MAX_IMAGES_PER_PAGE,
    MAX_TOTAL_EMBEDDED_IMAGE_BYTES,
    filter_chain_is_trusted,
    image_precheck_ok,
    shrink_factor,
)

pytestmark = pytest.mark.unit

pymupdf = pytest.importorskip("pymupdf")
pil_image = pytest.importorskip("PIL.Image")
pil_features = pytest.importorskip("PIL.features")

HAS_JPEG2000 = bool(pil_features.check_codec("jpg_2000"))


# ── Helpers ───────────────────────────────────────────────────────────


def _write_pdf(path: Path, build: Any) -> Path:
    """用 ``build(page)`` 往一页 PDF 里塞内容并落盘。"""
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=600, height=400)
        build(page)
        doc.save(str(path))
    finally:
        doc.close()
    return path


def _pdf_with_images(
    tmp_path: Path,
    count: int = 1,
    size: int = 20,
    mode: str = "RGB",
    fmt: str = "PNG",
    name: str = "with-images.pdf",
) -> Path:
    """生成一页含 ``count`` 张**互不相同**图片的 PDF（不同颜色 → 不同 xref）。"""
    path = tmp_path / name

    def _build(page: Any) -> None:
        for index in range(count):
            buffer = io.BytesIO()
            if mode == "L":
                # 灰度图只接受标量颜色。
                pixel = (index * 37) % 256
            elif mode == "RGBA":
                pixel = ((index * 37) % 256, (index * 91) % 256, (index * 143) % 256, 255)
            else:
                pixel = ((index * 37) % 256, (index * 91) % 256, (index * 143) % 256)
            image = pil_image.new(mode, (size, size), pixel)
            image.save(buffer, format=fmt)
            left = 10 + (index % 10) * 30
            top = 10 + (index // 10) * 30
            page.insert_image(
                pymupdf.Rect(left, top, left + 25, top + 25),
                stream=buffer.getvalue(),
            )

    return _write_pdf(path, _build)


def _decode_jpeg(data_url: str) -> Any:
    """把返回的 ``data:image/jpeg;base64,…`` 解回 PIL 图像。"""
    payload = base64.b64decode(data_url.split(",", 1)[1])
    return pil_image.open(io.BytesIO(payload)).convert("RGB")


def _spy_pixmap(monkeypatch: Any) -> List[Any]:
    """把 ``pymupdf.Pixmap`` 换成间谍 —— 记录每次调用。

    被调用时抛 ``AssertionError``（属于 ``Exception``，会被解码路径的
    ``except Exception`` 吞掉），但**调用记录不会消失** —— 断言
    ``calls == []`` 才是真正的判据：预检通过后一旦走到解码，这里就会
    留下痕迹。
    """
    calls: List[Any] = []

    def _spy(*args: Any, **_kwargs: Any) -> Any:
        calls.append(args)
        raise AssertionError("该路径不应解码任何位图")

    monkeypatch.setattr(pymupdf, "Pixmap", _spy)
    return calls


# ── CRITICAL-1：自带尺寸的编解码器必须在解码前被拒 ────────────────────


def test_untrusted_filter_chains_are_rejected():
    """码流自带真实尺寸的过滤器 → 字典尺寸不可信 → 不可信。"""
    assert filter_chain_is_trusted(None) is False
    assert filter_chain_is_trusted([]) is True
    assert filter_chain_is_trusted(["JPXDECODE"]) is False
    assert filter_chain_is_trusted(["JBIG2DECODE"]) is False
    assert filter_chain_is_trusted(["CCITTFAXDECODE"]) is False
    assert filter_chain_is_trusted(["FLATEDECODE"]) is True
    assert filter_chain_is_trusted(["DCTDECODE"]) is True
    # 链尾才是产生像素样本的编解码器；链头只是 ASCII 编码包装。
    assert filter_chain_is_trusted(["ASCII85DECODE", "FLATEDECODE"]) is True
    assert filter_chain_is_trusted(["ASCII85DECODE", "JPXDECODE"]) is False


@pytest.mark.skipif(not HAS_JPEG2000, reason="PIL 未编译 JPEG2000 编解码器")
def test_jpx_image_is_rejected_before_any_decode(tmp_path: Path, monkeypatch):
    """JPX 图（码流自带尺寸）→ 解码前被拒，且**绝不**走到 Pixmap。"""
    calls = _spy_pixmap(monkeypatch)
    path = _pdf_with_images(tmp_path, count=1, size=60, fmt="JPEG2000", name="jpx.pdf")

    result = read_pdf(
        path,
        workspace_path=str(tmp_path),
        include_images=True,
        embed_image_data=True,
    )

    assert calls == []
    assert result.pages[0].image_count == 1
    assert result.pages[0].images == []
    assert result.pages[0].images_omitted == 1


@pytest.mark.skipif(not HAS_JPEG2000, reason="PIL 未编译 JPEG2000 编解码器")
def test_forged_dimensions_do_not_bypass_the_precheck(tmp_path: Path, monkeypatch):
    """把真实位图的字典改成 /Width 10 /Height 10。

    预检若信了字典，就会按 10×10 放行、然后让 MuPDF 按码流真实尺寸申请
    位图 —— 这正是那条 2.1GB RSS 路径。这里必须解码前就拒。
    """
    path = _pdf_with_images(tmp_path, count=1, size=60, fmt="JPEG2000", name="forged.pdf")

    doc = pymupdf.open(str(path))
    try:
        xref = doc[0].get_images(full=True)[0][0]
        doc.xref_set_key(xref, "Width", "10")
        doc.xref_set_key(xref, "Height", "10")
        doc.saveIncr()
    finally:
        doc.close()

    calls = _spy_pixmap(monkeypatch)

    result = read_pdf(
        path,
        workspace_path=str(tmp_path),
        include_images=True,
        embed_image_data=True,
    )

    assert calls == []
    assert result.pages[0].image_count == 1
    assert result.pages[0].images == []
    assert result.pages[0].images_omitted == 1


def test_jpeg_dct_image_is_accepted(tmp_path: Path):
    """DCTDecode（MuPDF 按字典尺寸缩放解码）→ 字典尺寸可信 → 正常返回。"""
    path = _pdf_with_images(tmp_path, count=1, size=40, fmt="JPEG", name="dct.pdf")

    result = read_pdf(
        path,
        workspace_path=str(tmp_path),
        include_images=True,
        embed_image_data=True,
    )

    assert len(result.pages[0].images) == 1
    assert result.pages[0].images[0]["data_url"].startswith("data:image/jpeg")
    assert result.pages[0].images_omitted == 0


def test_raw_png_image_is_accepted(tmp_path: Path):
    """无过滤器的原始位图（PNG 插入后 PDF 里就是裸样本）→ 可信 → 正常返回。"""
    path = _pdf_with_images(tmp_path, count=1, size=40, name="raw.pdf")

    result = read_pdf(
        path,
        workspace_path=str(tmp_path),
        include_images=True,
        embed_image_data=True,
    )

    assert len(result.pages[0].images) == 1
    assert result.pages[0].images[0]["data_url"].startswith("data:image/jpeg")


# ── HIGH-2：include_images=False 时不枚举 ──────────────────────────────


def test_include_images_false_never_enumerates_images(tmp_path: Path, monkeypatch):
    """病理 PDF 的 get_images() 单页可达 0.1s —— 默认路径不该碰它。"""

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("include_images=False 时不应枚举图片")

    monkeypatch.setattr(pymupdf.Page, "get_images", _boom)

    path = _pdf_with_images(tmp_path, count=1)
    result = read_pdf(path, workspace_path=str(tmp_path), include_images=False)

    assert result.pages[0].images == []
    assert result.pages[0].image_count == 0
    assert result.pages[0].images_omitted == 0


# ── 解码前预检 ────────────────────────────────────────────────────────


def test_image_precheck_accepts_ordinary_image():
    assert image_precheck_ok(1, 100, 100, 8, "DeviceRGB") is True


def test_image_precheck_rejects_oversized_pixels():
    """16000×16000 的图 → 解码前就被拒（250MB+ 位图，压缩后可能只有几十 KB）。"""
    assert image_precheck_ok(1, 16000, 16000, 8, "DeviceRGB") is False


def test_image_precheck_rejects_oversized_decoded_bytes():
    """像素数达标但每像素字节数高（16bpc CMYK）→ 按解码字节数拒。"""
    assert image_precheck_ok(1, 4000, 3000, 16, "DeviceCMYK") is False


def test_image_precheck_rejects_unknown_dimensions():
    assert image_precheck_ok(1, 0, 100, 8, "DeviceRGB") is False


def test_oversized_image_is_skipped_but_read_still_succeeds(
    tmp_path: Path, monkeypatch
):
    """预算内的图跳过 → 该图不返回，但整份 PDF 仍然读得出来。"""
    monkeypatch.setattr("backend.office.pdf_images.MAX_EMBEDDED_IMAGE_PIXELS", 1)
    path = _pdf_with_images(tmp_path, count=1)

    result = read_pdf(
        path, workspace_path=str(tmp_path), include_images=True, embed_image_data=True
    )

    assert result.pages[0].images == []
    assert result.pages[0].image_count == 1
    assert result.pages[0].images_omitted == 1


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
    assert result.pages[0].images_omitted == 2


def test_non_numeric_max_images_per_page_is_treated_as_zero(tmp_path: Path):
    path = _pdf_with_images(tmp_path, count=1)

    result = read_pdf(
        path,
        workspace_path=str(tmp_path),
        include_images=True,
        max_images_per_page="abc",  # type: ignore[arg-type]
    )

    assert result.pages[0].images == []


# ── images_omitted 记账 ───────────────────────────────────────────────


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
    assert result.pages[0].images_omitted == 2


# ── 预算 ──────────────────────────────────────────────────────────────


def test_total_budget_caps_returned_images(tmp_path: Path):
    """把全文档预算压到极小 → 一张都放不下（预算按 base64 编码后计）。"""
    path = _pdf_with_images(tmp_path, count=2)

    result = read_pdf(
        path,
        workspace_path=str(tmp_path),
        include_images=True,
        embed_image_data=True,
        max_total_image_bytes=64,
    )

    assert result.pages[0].images == []
    assert result.pages[0].image_count == 2
    assert result.pages[0].images_omitted == 2


def test_default_total_budget_is_bounded():
    assert 0 < MAX_TOTAL_EMBEDDED_IMAGE_BYTES <= 20 * 1024 * 1024


def test_decode_count_is_capped_per_document(tmp_path: Path, monkeypatch):
    """解码次数封顶 —— 病理 PDF 的解码是 CPU 与内存的大头。"""
    monkeypatch.setattr("backend.office.pdf_images.MAX_IMAGE_DECODES_PER_DOCUMENT", 1)
    path = _pdf_with_images(tmp_path, count=3)

    result = read_pdf(
        path,
        workspace_path=str(tmp_path),
        include_images=True,
        embed_image_data=True,
    )

    assert len(result.pages[0].images) <= 1
    assert result.pages[0].image_count == 3


def test_decode_cap_constant_is_sane():
    assert 0 < MAX_IMAGE_DECODES_PER_DOCUMENT <= 1000


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
    calls = _spy_pixmap(monkeypatch)

    path = _pdf_with_images(tmp_path, count=1)
    result = read_pdf(
        path,
        workspace_path=str(tmp_path),
        include_images=True,
        embed_image_data=False,
    )

    assert calls == []
    assert len(result.pages[0].images) == 1


# ── 预览归一化（统一 JPEG + 缩放）────────────────────────────────────


def test_grayscale_image_is_converted_to_jpeg(tmp_path: Path):
    path = _pdf_with_images(tmp_path, count=1, mode="L")

    result = read_pdf(
        path, workspace_path=str(tmp_path), include_images=True, embed_image_data=True
    )

    assert result.pages[0].images[0]["data_url"].startswith("data:image/jpeg")


def test_alpha_image_is_converted_to_jpeg(tmp_path: Path):
    path = _pdf_with_images(tmp_path, count=1, mode="RGBA")

    result = read_pdf(
        path, workspace_path=str(tmp_path), include_images=True, embed_image_data=True
    )

    assert result.pages[0].images[0]["data_url"].startswith("data:image/jpeg")


def test_transparent_pixels_are_composited_on_white(tmp_path: Path):
    """PDF 的 alpha 在独立 SMask 里 —— 合成到白底（与 MuPDF 页面渲染一致）。"""
    pytest.importorskip("numpy")

    path = tmp_path / "alpha.pdf"

    def _build(page: Any) -> None:
        image = pil_image.new("RGBA", (40, 40), (0, 0, 0, 0))
        image.putpixel((20, 20), (255, 0, 0, 255))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        page.insert_image(pymupdf.Rect(10, 10, 110, 110), stream=buffer.getvalue())

    _write_pdf(path, _build)

    result = read_pdf(
        path, workspace_path=str(tmp_path), include_images=True, embed_image_data=True
    )

    entry = result.pages[0].images[0]
    decoded = _decode_jpeg(entry["data_url"])
    red, green, blue = decoded.getpixel((0, 0))
    assert red >= 250
    assert green >= 250
    assert blue >= 250


def test_shrink_factor_uses_power_of_two_semantics():
    """``Pixmap.shrink(n)`` 是除以 2**n** —— 因子必须按 2 的幂取。"""
    assert shrink_factor(1024) == 0
    assert shrink_factor(1025) == 1
    assert shrink_factor(2000) == 1
    assert shrink_factor(2048) == 1
    assert shrink_factor(4096) == 2


def test_large_image_is_downscaled_to_preview_edge(tmp_path: Path):
    """2000×2000 的图 → 预览最长边落在 [EDGE/2, EDGE] 区间。

    下界很重要：只断言「不超过 EDGE」的话，把图缩成 1×1 也算通过。
    """
    path = _pdf_with_images(tmp_path, count=1, size=2000, fmt="JPEG", name="big.pdf")

    result = read_pdf(
        path, workspace_path=str(tmp_path), include_images=True, embed_image_data=True
    )

    entry = result.pages[0].images[0]
    longest = max(entry["width"], entry["height"])
    assert MAX_EMBEDDED_IMAGE_EDGE // 2 <= longest <= MAX_EMBEDDED_IMAGE_EDGE


def test_high_entropy_image_is_not_dropped(tmp_path: Path):
    """高熵噪声图 JPEG 压不动 —— 应当逐级降质/缩放，而不是整张丢弃。"""
    path = tmp_path / "noise.pdf"

    def _build(page: Any) -> None:
        pixels = os.urandom(800 * 800 * 3)
        image = pil_image.frombytes("RGB", (800, 800), pixels)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=95)
        page.insert_image(pymupdf.Rect(0, 0, 800, 800), stream=buffer.getvalue())

    _write_pdf(path, _build)

    result = read_pdf(
        path, workspace_path=str(tmp_path), include_images=True, embed_image_data=True
    )

    assert len(result.pages[0].images) == 1
    assert result.pages[0].images[0]["data_url"].startswith("data:image/jpeg")


def test_preview_edge_constant_is_sane():
    assert 0 < MAX_EMBEDDED_IMAGE_EDGE <= 2048
    assert 0 < MAX_EMBEDDED_IMAGE_PIXELS <= 100_000_000


def test_result_carries_no_unexpected_image_keys(tmp_path: Path):
    """带像素的图片条目字段是稳定的 —— 前端按这些键渲染。"""
    path = _pdf_with_images(tmp_path, count=1)

    result = read_pdf(
        path, workspace_path=str(tmp_path), include_images=True, embed_image_data=True
    )

    entry: Dict[str, Any] = result.pages[0].images[0]
    assert set(entry) == {"index", "width", "height", "ext", "size_bytes", "data_url"}
