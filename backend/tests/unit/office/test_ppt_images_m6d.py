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


def test_read_ppt_total_budget_exhaustion_counts_omitted(
    tmp_path: Path, monkeypatch
) -> None:
    deck = _make_deck(tmp_path / "deck.pptx", pictures=2)
    monkeypatch.setattr(
        "backend.office.ppt.PPT_IMAGE_TOTAL_RAW_BUDGET", len(_png_bytes())
    )

    result = read_ppt(deck, include_images=True, embed_image_data=True)
    slide = result.slides[0]

    # 第一张恰好用尽总预算，第二张只能计入 omitted —— 预算跨页/跨图共享。
    assert len(slide.images) == 1
    assert slide.images[0]["data_url"].startswith("data:image/png;base64,")
    assert slide.images_omitted == 1


def test_read_ppt_inspection_cap_counts_remaining_pictures(
    tmp_path: Path, monkeypatch
) -> None:
    deck = _make_deck(tmp_path / "deck.pptx", pictures=3)
    monkeypatch.setattr("backend.office.ppt.PPT_IMAGE_MAX_INSPECTIONS", 1)

    result = read_ppt(deck, include_images=True)
    slide = result.slides[0]

    assert len(slide.images) == 1
    assert slide.images_omitted == 2


def test_extract_slide_images_skips_linked_pictures() -> None:
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    from backend.office.ppt import _extract_slide_images

    class _Image:
        content_type = "image/png"
        size = (10, 10)
        blob = b"1234"

    class _Shape:
        name = "Pic"

        def __init__(self, image) -> None:
            self.shape_type = MSO_SHAPE_TYPE.PICTURE
            self._image = image

        @property
        def image(self):
            if self._image is None:
                # 链接图没有内嵌 part —— python-pptx 访问 image 会抛错。
                raise AttributeError("linked picture")
            return self._image

    class _Slide:
        shapes = [_Shape(None), _Shape(_Image())]

    budget = {"remaining": 10**6, "inspected": 0}
    images, omitted = _extract_slide_images(
        _Slide(), max_images=3, embed_image_data=False, budget=budget
    )

    # 链接图内容不在文件里，不算「被裁掉」；内嵌图正常返回。
    assert len(images) == 1
    assert omitted == 0
