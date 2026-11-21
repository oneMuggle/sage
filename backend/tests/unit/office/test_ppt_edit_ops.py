"""Unit tests for M2 PowerPoint deep-edit ops and read-side fields."""

from __future__ import annotations

import io
from pathlib import Path

from backend.office.edit import update_pptx
from backend.office.ppt import read_ppt


def _png_bytes(color: str) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _make_deck(path: Path, *, images: bool = False) -> Path:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    blank = prs.slide_layouts[6]
    first = prs.slides.add_slide(blank)
    box = first.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
    box.text_frame.text = "Alpha"
    first.notes_slide.notes_text_frame.text = "first notes"
    if images:
        first.shapes.add_picture(
            io.BytesIO(_png_bytes("red")), Inches(1), Inches(2), width=Inches(1)
        )
    second = prs.slides.add_slide(blank)
    second_box = second.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
    second_box.text_frame.text = "Beta"
    prs.save(str(path))
    return path


def _titles(path: Path) -> list[str]:
    result = read_ppt(path)
    return [slide.text_blocks[0] if slide.text_blocks else "" for slide in result.slides]


def test_duplicate_slide_copies_text_notes_and_picture(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path / "deck.pptx", images=True)

    saved, results = update_pptx(deck, [{"op": "duplicate_slide", "index": 0, "position": 1}])

    assert saved is True
    assert results[0]["ok"] is True
    result = read_ppt(deck)
    assert len(result.slides) == 3
    assert result.slides[1].text_blocks[0] == "Alpha"
    assert result.slides[1].notes == "first notes"
    assert result.slides[1].image_count == 1


def test_move_slide_reorders_and_delete_still_works(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path / "deck.pptx")

    saved, results = update_pptx(deck, [{"op": "move_slide", "index": 0, "to": 1}])

    assert saved is True
    assert results[0]["ok"] is True
    assert _titles(deck) == ["Beta", "Alpha"]

    saved, results = update_pptx(deck, [{"op": "delete_slide", "index": 0}])
    assert saved is True
    assert results[0]["ok"] is True
    assert _titles(deck) == ["Alpha"]


def test_append_slide_with_layout_and_placeholders(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path / "deck.pptx")
    from pptx import Presentation

    prs = Presentation(str(deck))
    layout = prs.slide_layouts[1]
    layout_name = layout.name
    title_idx = layout.placeholders[0].placeholder_format.idx
    body_idx = layout.placeholders[1].placeholder_format.idx

    saved, results = update_pptx(
        deck,
        [
            {
                "op": "append_slide",
                "layout": layout_name,
                "placeholders": {
                    str(title_idx): "新标题",
                    str(body_idx): "新正文",
                },
                "position": 0,
            }
        ],
    )

    assert saved is True
    assert results[0]["ok"] is True
    assert results[0]["layout"] == layout_name
    result = read_ppt(deck)
    assert result.slides[0].layout == layout_name
    assert result.slides[0].title == "新标题"
    assert "新正文" in result.slides[0].text_blocks


def test_append_slide_rejects_unknown_layout(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path / "deck.pptx")

    saved, results = update_pptx(
        deck, [{"op": "append_slide", "layout": "Definitely Missing Layout"}]
    )

    assert saved is False
    assert results[0]["ok"] is False
    assert "layout_not_found" in results[0]["error"]


def test_set_run_format_by_find(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path / "deck.pptx")

    saved, results = update_pptx(
        deck,
        [
            {
                "op": "set_run_format",
                "index": 0,
                "find": "Alpha",
                "bold": True,
                "font_size": 20,
                "color": "FF0000",
            }
        ],
    )

    assert saved is True
    assert results[0]["ok"] is True
    from pptx import Presentation

    prs = Presentation(str(deck))
    runs = [
        run
        for shape in prs.slides[0].shapes
        if shape.has_text_frame
        for paragraph in shape.text_frame.paragraphs
        for run in paragraph.runs
    ]
    assert runs
    assert runs[0].font.bold is True
    assert runs[0].font.size.pt == 20
    assert str(runs[0].font.color.rgb) == "FF0000"


def test_replace_image_keeps_one_picture_at_same_position(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path / "deck.pptx", images=True)
    blue = _png_bytes("blue")
    blue_path = tmp_path / "blue.png"
    blue_path.write_bytes(blue)

    saved, results = update_pptx(
        deck,
        [{"op": "replace_image", "index": 0, "shape_index": 0, "path": str(blue_path)}],
    )

    assert saved is True
    assert results[0]["ok"] is True
    from pptx import Presentation

    prs = Presentation(str(deck))
    pictures = [shape for shape in prs.slides[0].shapes if shape.shape_type == 13]
    assert len(pictures) == 1
    assert pictures[0].image.blob == blue


def test_add_chart_and_read_back(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path / "deck.pptx")

    saved, results = update_pptx(
        deck,
        [
            {
                "op": "add_chart",
                "index": 0,
                "type": "column",
                "categories": ["Q1", "Q2"],
                "series": [{"name": "销售", "values": [1, 2]}],
                "title": "季度",
            }
        ],
    )

    assert saved is True
    assert results[0]["ok"] is True
    result = read_ppt(deck)
    charts = result.slides[0].charts
    assert charts
    assert charts[0]["categories"] == ["Q1", "Q2"]
    assert charts[0]["series"][0]["name"] == "销售"
    assert charts[0]["series"][0]["values"] == [1.0, 2.0]
    assert "COLUMN" in charts[0]["type"]


def test_read_ppt_truncates_large_chart_series(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path / "deck.pptx")
    categories = [f"C{index}" for index in range(60)]

    saved, results = update_pptx(
        deck,
        [
            {
                "op": "add_chart",
                "index": 0,
                "type": "column",
                "categories": categories,
                "series": [{"name": "S", "values": list(range(60))}],
            }
        ],
    )
    assert saved is True
    assert results[0]["ok"] is True

    chart = read_ppt(deck).slides[0].charts[0]
    assert len(chart["categories"]) == 50
    assert len(chart["series"][0]["values"]) == 50
    assert chart["truncated"] is True


def test_read_ppt_exposes_layout_and_placeholders(tmp_path: Path) -> None:
    from pptx import Presentation

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "标题"
    deck = tmp_path / "layout.pptx"
    prs.save(str(deck))

    result = read_ppt(deck)

    assert result.slides[0].layout
    placeholders = result.slides[0].placeholders
    assert placeholders
    assert any(item["text"] == "标题" for item in placeholders)
