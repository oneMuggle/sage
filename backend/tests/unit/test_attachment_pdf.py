"""聊天附件 PDF 页级解析与图表抽取单元测试（2026-11-15）。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

pymupdf = pytest.importorskip("pymupdf")

from backend.services import attachment_pdf as ap  # noqa: E402
from backend.services.multimodal.media_store import MediaKind, MediaStore  # noqa: E402


def _png(width: int = 120, height: int = 90, color=(200, 30, 30)) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), False)
    pix.set_rect(pix.irect, color)
    return pix.tobytes("png")


def _make_pdf(pages) -> bytes:
    """pages: [{text: str|None, images: [(rect, bytes)|None], captions: [(pos, text)]}]"""
    doc = pymupdf.open()
    for spec in pages:
        page = doc.new_page(width=400, height=500)
        if spec.get("text"):
            page.insert_text((50, 60), spec["text"])
        for rect, data in spec.get("images") or []:
            page.insert_image(pymupdf.Rect(*rect), stream=data)
        for pos, text in spec.get("captions") or []:
            page.insert_text(pos, text)
    data = doc.tobytes()
    doc.close()
    return data


class TestExtractPdfPages:
    def test_keeps_page_numbers(self):
        pdf = _make_pdf([{"text": "alpha content"}, {"text": "beta content"}])
        pages = ap.extract_pdf_pages(pdf)
        assert [(p.page_number, p.text.strip()) for p in pages] == [
            (1, "alpha content"),
            (2, "beta content"),
        ]

    def test_render_page_marked_text(self):
        pdf = _make_pdf([{"text": "alpha content"}, {"text": "beta content"}])
        marked = ap.render_page_marked_text(ap.extract_pdf_pages(pdf))
        assert "--- page 1 ---" in marked
        assert "--- page 2 ---" in marked
        assert marked.index("alpha content") < marked.index("beta content")

    def test_ocr_fallback_when_text_missing(self, monkeypatch):
        pdf = _make_pdf([{"text": None}])

        def _fake_ocr(page, text):
            return "OCR TEXT FROM SCAN"

        import backend.office.ocr as ocr_mod

        monkeypatch.setattr(ocr_mod, "ocr_page_if_needed", _fake_ocr)
        pages = ap.extract_pdf_pages(pdf)
        assert pages
        assert "OCR TEXT FROM SCAN" in pages[0].text

    def test_empty_text_pages_are_omitted_from_marked_text(self):
        pdf = _make_pdf([{"text": None}, {"text": "second page"}])
        marked = ap.render_page_marked_text(ap.extract_pdf_pages(pdf))
        assert "--- page 1 ---" not in marked
        assert "--- page 2 ---" in marked


class TestExtractPdfFigures:
    def test_extracts_embedded_image_with_caption(self):
        png = _png()
        pdf = _make_pdf(
            [
                {
                    "text": "intro",
                    "images": [((50, 70, 250, 220), png)],
                    "captions": [((50, 250), "Figure 1 Test chart")],
                }
            ]
        )
        figs = ap.extract_pdf_figures(pdf)
        assert len(figs) == 1
        fig = figs[0]
        assert fig.page_number == 1
        assert fig.ext == "png"
        assert fig.image_bytes
        assert fig.width == 120
        assert fig.height == 90
        assert "Figure 1" in fig.caption
        assert fig.bbox[2] > fig.bbox[0]

    def test_skips_tiny_images(self):
        small = _png(width=30, height=20)
        pdf = _make_pdf([{"images": [((50, 70, 100, 100), small)]}])
        assert ap.extract_pdf_figures(pdf) == []

    def test_skips_full_page_background(self):
        full = _png(width=300, height=400)
        pdf = _make_pdf([{"images": [((0, 0, 400, 500), full)]}])
        assert ap.extract_pdf_figures(pdf) == []

    def test_deduplicates_same_image_across_pages(self):
        png = _png()
        pdf = _make_pdf(
            [
                {"images": [((50, 70, 250, 220), png)]},
                {"images": [((50, 70, 250, 220), png)]},
            ]
        )
        figs = ap.extract_pdf_figures(pdf)
        assert len(figs) == 1

    def test_falls_back_to_plain_text_below_image(self):
        png = _png()
        pdf = _make_pdf(
            [
                {
                    "images": [((50, 70, 250, 220), png)],
                    "captions": [((50, 250), "A plain explanation")],
                }
            ]
        )
        figs = ap.extract_pdf_figures(pdf)
        assert len(figs) == 1
        assert "plain explanation" in figs[0].caption


class TestFigureManifest:
    def _store_and_ref(self, tmp_path, pdf_bytes):
        store = MediaStore(root=tmp_path / "media")
        ref = store.save(
            pdf_bytes,
            MediaKind.DOCUMENT,
            source="chat_upload",
            metadata={"original_filename": "paper.pdf"},
            ext="pdf",
        )
        return store, ref

    def test_persists_manifest_and_caches(self, tmp_path):
        png = _png()
        pdf = _make_pdf(
            [
                {
                    "images": [((50, 70, 250, 220), png)],
                    "captions": [((50, 250), "Figure 1 Test chart")],
                }
            ]
        )
        store, ref = self._store_and_ref(tmp_path, pdf)

        first = ap.get_or_build_figure_manifest(store, ref, pdf)
        assert len(first) == 1
        manifest_path = ap.figures_manifest_path(store.root / ref.file_path)
        assert manifest_path.exists()

        figure_ref, figure_bytes = store.load(first[0]["media_id"])
        assert figure_ref.kind == MediaKind.IMAGE
        assert figure_ref.metadata["source_media_id"] == ref.id
        assert figure_ref.metadata["page"] == 1
        assert figure_bytes.startswith(b"\x89PNG")

        second = ap.get_or_build_figure_manifest(store, ref, pdf)
        assert [f["media_id"] for f in second] == [f["media_id"] for f in first]
        assert len(list(store.root.rglob("*.png"))) == 1

    def test_corrupt_manifest_rebuilds(self, tmp_path):
        png = _png()
        pdf = _make_pdf([{"images": [((50, 70, 250, 220), png)]}])
        store, ref = self._store_and_ref(tmp_path, pdf)

        manifest_path = ap.figures_manifest_path(store.root / ref.file_path)
        manifest_path.write_text("{not json", encoding="utf-8")

        rebuilt = ap.get_or_build_figure_manifest(store, ref, pdf)
        assert len(rebuilt) == 1

    def test_render_manifest_xml_contains_media_url(self):
        xml = ap.render_figure_manifest_xml(
            "paper.pdf",
            [
                {
                    "figure_id": "f-p12-1",
                    "page": 12,
                    "caption": "图 3 系统架构",
                    "media_id": "abc123def456",
                    "media_url": "/api/v1/media/abc123def456",
                }
            ],
        )
        assert "<attached_figures" in xml
        assert 'page="12"' in xml
        assert "/api/v1/media/abc123def456" in xml


class TestExtractDocumentTextIntegration:
    def test_pdf_extraction_has_page_markers(self):
        from backend.api.chat_attachment_routes import _extract_document_text

        pdf = _make_pdf([{"text": "alpha content"}, {"text": "beta content"}])
        text = _extract_document_text(pdf, "pdf")
        assert "--- page 1 ---" in text
        assert "--- page 2 ---" in text
