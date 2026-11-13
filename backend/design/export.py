"""Design artifact export pipeline.

Exports design artifacts (HTML) to deliverable file formats:

- **PDF**: via LibreOffice headless (cross-platform), reusing the same
  ``_locate_soffice`` helper from ``office/export_pdf``. Falls back to a
  simple reportlab-based HTML→PDF renderer when soffice is unavailable.
- **ZIP**: bundles self-contained HTML (with inlined CSS/JS) into a ZIP
  archive, suitable for sharing or offline viewing.
- **HTML**: returns the bundled HTML as-is (for backward compatibility).

Python 3.8-compatible syntax (typing.* generics, no PEP 604) so the
module can be cherry-picked to ``release/win7``.
"""
from __future__ import annotations

import logging
import re
import subprocess
import threading
import zipfile
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from backend.office.export_pdf import _locate_soffice

logger = logging.getLogger(__name__)

__all__ = ["DesignExportResult", "DesignExporter"]

#: Concurrent soffice processes share a user profile and clash. Serialize
#: all design exports through a single lock (same pattern as office/export_pdf).
_EXPORT_LOCK = threading.Lock()


class DesignExportResult(BaseModel):
    """Result of a design artifact export.

    ``ok`` indicates whether the export succeeded. ``file_path`` is populated
    on success for PDF/ZIP formats. ``html_content`` is populated for the
    "html" format. ``error`` contains a human-readable failure reason.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(description="Export success flag")
    format: str = Field(description="Output format: pdf | zip | html")
    file_path: Optional[str] = Field(
        default=None,
        description="Absolute path to the exported file (PDF/ZIP)",
    )
    html_content: Optional[str] = Field(
        default=None,
        description="HTML content (only populated when format=html)",
    )
    error: Optional[str] = Field(
        default=None,
        description="Failure reason (populated when ok=False)",
    )


class DesignExporter:
    """Export design artifacts to PDF / ZIP / HTML.

    Usage::

        exporter = DesignExporter()
        result = exporter.export(html="<html>...", output_dir=Path("/tmp"), format="pdf")
        if result.ok:
            print(f"Exported to: {result.file_path}")
    """

    def export(
        self,
        html: str,
        output_dir: Path,
        format: str,
        *,
        filename: Optional[str] = None,
        timeout_seconds: int = 120,
    ) -> DesignExportResult:
        """Export HTML to the specified format.

        Args:
            html: The HTML content to export.
            output_dir: Directory where the output file will be written.
            format: Target format — "pdf", "zip", or "html".
            filename: Optional output filename (without extension). Defaults
                to "design_export".
            timeout_seconds: Wall-clock limit for the soffice subprocess.

        Returns:
            DesignExportResult with success flag and output path/content.
        """
        with _EXPORT_LOCK:
            try:
                return self._export_inner(
                    html, output_dir, format,
                    filename=filename,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 — contract: never raise
                logger.exception("Design export crashed unexpectedly")
                return DesignExportResult(
                    ok=False,
                    format=format,
                    error=f"导出失败：内部错误（{type(exc).__name__}，详见日志）",
                )

    def _export_inner(
        self,
        html: str,
        output_dir: Path,
        format: str,
        *,
        filename: Optional[str],
        timeout_seconds: int,
    ) -> DesignExportResult:
        """Inner export logic (called under lock)."""
        if format not in ("pdf", "zip", "html"):
            return DesignExportResult(
                ok=False,
                format=format,
                error=f"不支持的导出格式 {format!r}（仅支持 pdf / zip / html）",
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        base_name = filename or "design_export"

        if format == "html":
            return DesignExportResult(
                ok=True,
                format="html",
                html_content=html,
            )

        if format == "zip":
            return self._export_zip(html, output_dir, base_name)

        # format == "pdf"
        return self._export_pdf(html, output_dir, base_name, timeout_seconds)

    def _export_zip(
        self,
        html: str,
        output_dir: Path,
        base_name: str,
    ) -> DesignExportResult:
        """Bundle HTML into a self-contained ZIP archive."""
        zip_path = output_dir / f"{base_name}.zip"
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("index.html", html)
            logger.info("Design export to ZIP succeeded: %s", zip_path)
            return DesignExportResult(
                ok=True,
                format="zip",
                file_path=str(zip_path),
            )
        except Exception as exc:
            logger.warning("Design export to ZIP failed: %s", exc)
            return DesignExportResult(
                ok=False,
                format="zip",
                error=f"ZIP 导出失败: {exc}",
            )

    def _export_pdf(
        self,
        html: str,
        output_dir: Path,
        base_name: str,
        timeout_seconds: int,
    ) -> DesignExportResult:
        """Convert HTML to PDF via soffice headless.

        Falls back to reportlab when soffice is unavailable.
        """
        pdf_path = output_dir / f"{base_name}.pdf"

        # Try soffice first
        soffice_path = _locate_soffice()
        if soffice_path is not None:
            result = self._convert_with_libreoffice(
                soffice_path, html, output_dir, base_name, timeout_seconds,
            )
            if result.ok:
                return result
            logger.info("LibreOffice PDF export failed: %s", result.error)
        else:
            logger.info("LibreOffice (soffice) not found — attempting reportlab fallback")

        # Fallback: reportlab
        return self._convert_with_reportlab(html, pdf_path)

    def _convert_with_libreoffice(
        self,
        soffice_path: str,
        html: str,
        output_dir: Path,
        base_name: str,
        timeout_seconds: int,
    ) -> DesignExportResult:
        """Run soffice --headless --convert-to pdf on a temporary HTML file."""
        # Write HTML to a temp file in the output directory (soffice writes
        # output next to the source).
        html_path = output_dir / f"{base_name}.html"
        try:
            html_path.write_text(html, encoding="utf-8")
        except Exception as exc:
            return DesignExportResult(
                ok=False,
                format="pdf",
                error=f"无法写入临时 HTML 文件: {exc}",
            )

        cmd = [
            soffice_path,
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(html_path),
        ]
        logger.info("Design export to PDF via LibreOffice: %s", cmd)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "LibreOffice conversion exceeded %ss — child process killed",
                timeout_seconds,
            )
            self._cleanup_temp_html(html_path)
            return DesignExportResult(
                ok=False,
                format="pdf",
                error=f"LibreOffice 转换超时（上限 {timeout_seconds}s），进程已终止",
            )
        except OSError as exc:
            logger.warning("LibreOffice executable could not be launched: %s", exc)
            self._cleanup_temp_html(html_path)
            return DesignExportResult(
                ok=False,
                format="pdf",
                error=f"无法启动 LibreOffice: {exc}",
            )

        # Clean up the temp HTML file
        self._cleanup_temp_html(html_path)

        pdf_path = output_dir / f"{base_name}.pdf"
        if proc.returncode != 0:
            stderr_tail = (
                proc.stderr[-400:].decode("utf-8", "replace").strip()
                if proc.stderr else ""
            )
            logger.warning(
                "LibreOffice conversion failed (exit code %s): %s",
                proc.returncode,
                stderr_tail,
            )
            return DesignExportResult(
                ok=False,
                format="pdf",
                error=(
                    f"LibreOffice 转换失败（exit code {proc.returncode}）："
                    f"{stderr_tail or '无错误输出'}"
                ),
            )

        if not pdf_path.exists():
            logger.warning(
                "LibreOffice reported success but output PDF is missing: %s",
                pdf_path,
            )
            return DesignExportResult(
                ok=False,
                format="pdf",
                error="LibreOffice 报告成功，但未找到输出 PDF 文件",
            )

        logger.info("Design export to PDF succeeded: %s", pdf_path)
        return DesignExportResult(
            ok=True,
            format="pdf",
            file_path=str(pdf_path),
        )

    def _convert_with_reportlab(
        self,
        html: str,
        pdf_path: Path,
    ) -> DesignExportResult:
        """Fallback: render HTML to PDF using reportlab's Paragraph/Frame.

        This is a simplified renderer — it won't preserve complex CSS layouts,
        but it produces a readable PDF for basic content.
        """
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate
        except ImportError:
            logger.warning("reportlab not available — PDF export failed")
            return DesignExportResult(
                ok=False,
                format="pdf",
                error="PDF 导出失败：未找到 LibreOffice 且 reportlab 未安装",
            )

        try:
            # Strip HTML tags for plain-text rendering (reportlab Paragraph
            # supports a subset of HTML, but full design HTML is too complex).
            text = re.sub(r"<[^>]+>", "", html)
            text = re.sub(r"\s+", " ", text).strip()

            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=A4,
                title="Design Export",
            )
            styles = getSampleStyleSheet()
            story = [Paragraph(text, styles["Normal"])]
            doc.build(story)

            if not pdf_path.exists():
                return DesignExportResult(
                    ok=False,
                    format="pdf",
                    error="reportlab 渲染完成，但未找到输出 PDF 文件",
                )

            logger.info("Design export to PDF via reportlab succeeded: %s", pdf_path)
            return DesignExportResult(
                ok=True,
                format="pdf",
                file_path=str(pdf_path),
            )
        except Exception as exc:
            logger.warning("reportlab PDF export failed: %s", exc)
            return DesignExportResult(
                ok=False,
                format="pdf",
                error=f"reportlab 渲染失败: {exc}",
            )

    @staticmethod
    def _cleanup_temp_html(html_path: Path) -> None:
        """Remove the temporary HTML file after soffice conversion."""
        try:
            if html_path.exists():
                html_path.unlink()
        except Exception as exc:
            logger.debug("Failed to clean up temp HTML %s: %s", html_path, exc)
