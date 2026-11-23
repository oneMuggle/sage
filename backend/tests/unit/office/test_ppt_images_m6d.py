"""M6d：PPT 内嵌图片的读侧提取（include_images / 预算）。

与 PDF 的契约保持一致：
- ``include_images=False``（默认）时**完全不枚举**图片 → ``images`` 为空、
  ``images_omitted=0``；
- ``include_images=True`` 时返回元数据，``embed_image_data=False`` 不含
  ``data_url``（不解码像素成 base64）；
- ``embed_image_data=True`` 时受单图 / 全文档预算约束，超限的图片计入
  ``images_omitted``。
"""

from __future__ import annotations

import io
from pathlib import Path

from backend.office.ppt import read_ppt


def _png_bytes(width: int = 12, height: int = 8, color: str = "red") -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _make_deck(path: Path, *, pictures: int = 1) -> Path:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    blank = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank)
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
    box.text_frame.text = "Alpha"
    for i in range(pictures):
        slide.shapes.add_picture(
            io.BytesIO(_png_bytes()), Inches(1 + i), Inches(2), width=Inches(1)
        )
    prs.save(str(path))
    return path


def test_read_ppt_does_not_enumerate_images_by_default(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path / "deck.pptx")

    result = read_ppt(deck)
    slide = result.slides[0]

    assert slide.image_count == 1
    assert slide.images == []
    assert slide.images_omitted == 0


def test_read_ppt_returns_image_metadata_without_pixels(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path / "deck.pptx")

    result = read_ppt(deck, include_images=True)
    images = result.slides[0].images

    assert len(images) == 1
    image = images[0]
    assert image["content_type"] == "image/png"
    assert image["width_px"] == 12
    assert image["height_px"] == 8
    assert image["bytes"] > 0
    assert "data_url" not in image


def test_read_ppt_embeds_data_url_when_requested(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path / "deck.pptx")

    result = read_ppt(deck, include_images=True, embed_image_data=True)
    images = result.slides[0].images

    assert len(images) == 1
    assert images[0]["data_url"].startswith("data:image/png;base64,")
    assert result.slides[0].images_omitted == 0


def test_read_ppt_respects_per_slide_cap(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path / "deck.pptx", pictures=3)

    result = read_ppt(deck, include_images=True, max_images_per_slide=2)
    slide = result.slides[0]

    assert slide.image_count == 3
    assert len(slide.images) == 2
    assert slide.images_omitted == 1


def test_read_ppt_skips_oversized_image_when_embedding(
    tmp_path: Path, monkeypatch
) -> None:
    deck = _make_deck(tmp_path / "deck.pptx")
    monkeypatch.setattr("backend.office.ppt.PPT_IMAGE_MAX_RAW_BYTES", 16)

    result = read_ppt(deck, include_images=True, embed_image_data=True)
    slide = result.slides[0]

    assert slide.images == []
    assert slide.images_omitted == 1


def test_read_ppt_oversized_image_keeps_metadata_without_pixels(
    tmp_path: Path, monkeypatch
) -> None:
    deck = _make_deck(tmp_path / "deck.pptx")
    monkeypatch.setattr("backend.office.ppt.PPT_IMAGE_MAX_RAW_BYTES", 16)

    result = read_ppt(deck, include_images=True)
    images = result.slides[0].images

    assert len(images) == 1
    assert "data_url" not in images[0]
