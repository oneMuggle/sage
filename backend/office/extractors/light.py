"""Light extraction backend (M6b): wrap existing format readers as one shape.

No new dependencies: python-docx / openpyxl / python-pptx / PyMuPDF already
power the per-format readers. Output is Markdown plus anchored blocks so
RAG/compare can point back to page/paragraph/sheet/slide.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .base import ExtractedBlock, StructuredDocument
from .tables import assess_table_complexity, describe_complexity, table_markdown

_SUPPORTED = (".docx", ".xlsx", ".pptx", ".pdf", ".csv")
_MAX_ROWS_PER_SHEET = 2000


class LightExtractor:
    """Default backend built on the existing readers."""

    name = "light"

    def supports(self, suffix: str) -> bool:
        return suffix.lower() in _SUPPORTED

    def extract(self, path: Path) -> StructuredDocument:
        suffix = path.suffix.lower()
        if suffix == ".docx":
            return self._extract_docx(path)
        if suffix in (".xlsx", ".csv"):
            return self._extract_excel(path, suffix)
        if suffix == ".pptx":
            return self._extract_pptx(path)
        return self._extract_pdf(path)

    def _extract_docx(self, path: Path) -> StructuredDocument:
        from ..word import read_docx

        result = read_docx(path)
        lines: List[str] = []
        blocks: List[ExtractedBlock] = []
        for index, paragraph in enumerate(result.paragraphs):
            if not paragraph.text.strip():
                continue
            if paragraph.level > 0:
                prefix = "#" * min(paragraph.level, 6)
                lines.append(f"{prefix} {paragraph.text}")
                block_type = "heading"
            else:
                lines.append(paragraph.text)
                block_type = "paragraph"
            lines.append("")
            blocks.append(
                ExtractedBlock(
                    type=block_type,
                    text=paragraph.text,
                    anchor={"paragraph_index": index},
                )
            )
        for table_index, table in enumerate(result.tables):
            markdown = table_markdown(table.rows)
            if not markdown:
                continue
            lines.append(markdown)
            lines.append("")
            blocks.append(
                ExtractedBlock(
                    type="table",
                    text=markdown,
                    anchor={"table_index": table_index},
                )
            )
        return StructuredDocument(
            source_path=path.name,
            format="docx",
            extractor=self.name,
            markdown="\n".join(lines).strip(),
            blocks=blocks,
        )

    def _extract_excel(self, path: Path, suffix: str) -> StructuredDocument:
        from ..excel import read_csv, read_xlsx

        result = read_csv(path) if suffix == ".csv" else read_xlsx(path)
        lines: List[str] = []
        blocks: List[ExtractedBlock] = []
        warnings: List[Dict[str, str]] = []
        for sheet in result.sheets:
            lines.append(f"## {sheet.name}")
            lines.append("")
            rows = sheet.rows[:_MAX_ROWS_PER_SHEET]
            if len(sheet.rows) > _MAX_ROWS_PER_SHEET:
                warnings.append(
                    {
                        "code": "sheet_rows_truncated",
                        "message": f"sheet {sheet.name} 超过 {_MAX_ROWS_PER_SHEET} 行，仅提取前 {_MAX_ROWS_PER_SHEET} 行",
                    }
                )
            if rows:
                markdown = table_markdown(rows)
                lines.append(markdown)
                lines.append("")
                blocks.append(
                    ExtractedBlock(
                        type="table",
                        text=markdown,
                        anchor={"sheet": sheet.name, "rows": len(rows)},
                    )
                )
        return StructuredDocument(
            source_path=path.name,
            format="csv" if suffix == ".csv" else "xlsx",
            extractor=self.name,
            markdown="\n".join(lines).strip(),
            blocks=blocks,
            warnings=warnings,
        )

    def _extract_pptx(self, path: Path) -> StructuredDocument:
        from ..ppt import read_ppt

        result = read_ppt(path)
        lines: List[str] = []
        blocks: List[ExtractedBlock] = []
        for slide in result.slides:
            title = slide.title or f"Slide {slide.index + 1}"
            lines.append(f"## {title}")
            for text in slide.text_blocks:
                lines.append(f"- {text}")
            if slide.notes:
                lines.append(f"> 备注: {slide.notes}")
            lines.append("")
            blocks.append(
                ExtractedBlock(
                    type="slide",
                    text="\n".join([title, *slide.text_blocks]),
                    anchor={"slide": slide.index},
                )
            )
        return StructuredDocument(
            source_path=path.name,
            format="pptx",
            extractor=self.name,
            markdown="\n".join(lines).strip(),
            blocks=blocks,
        )

    def _extract_pdf(self, path: Path) -> StructuredDocument:
        from ..pdf import read_pdf

        # M6b: 打开无边框表格探测 —— 只判断"有没有疑似无边框表格"，
        # 探测结果不进入正文，由 service 决定是否换结构化后端兜底。
        result = read_pdf(
            path,
            workspace_path=str(path.parent),
            probe_borderless_tables=True,
        )
        lines: List[str] = []
        blocks: List[ExtractedBlock] = []
        warnings: List[Dict[str, str]] = []
        for page in result.pages:
            lines.append(f"--- page {page.page_number} ---")
            text = page.text.strip()
            if text:
                lines.append(text)
            table_blocks: List[ExtractedBlock] = []
            for table_index, table in enumerate(page.tables):
                markdown = table_markdown(table)
                if not markdown:
                    continue
                lines.append(markdown)
                table_blocks.append(
                    ExtractedBlock(
                        type="table",
                        text=markdown,
                        anchor={"page": page.page_number, "table_index": table_index},
                    )
                )
            lines.append("")
            blocks.append(
                ExtractedBlock(
                    type="page",
                    text=text,
                    anchor={"page": page.page_number},
                )
            )
            blocks.extend(table_blocks)
        diagnostics = dict(result.table_diagnostics)
        reasons = assess_table_complexity(diagnostics)
        if reasons:
            warnings.append(
                {
                    "code": "table_complex",
                    "message": f"检测到复杂表格：{describe_complexity(reasons)}",
                }
            )
        return StructuredDocument(
            source_path=path.name,
            format="pdf",
            extractor=self.name,
            markdown="\n".join(lines).strip(),
            blocks=blocks,
            warnings=warnings,
            table_diagnostics=diagnostics,
        )
