"""Tests for design artifact export pipeline (M1)."""
from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import patch

from backend.design.export import DesignExporter, DesignExportResult

SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head><title>Test Design</title></head>
<body>
<h1>Hello, Design!</h1>
<p>This is a test artifact.</p>
</body>
</html>"""


class TestDesignExportResult:
    """Test DesignExportResult model."""

    def test_success_pdf(self):
        """Test success result for PDF format."""
        result = DesignExportResult(
            ok=True,
            format="pdf",
            file_path="/tmp/design.pdf",
        )
        assert result.ok is True
        assert result.format == "pdf"
        assert result.file_path == "/tmp/design.pdf"
        assert result.html_content is None
        assert result.error is None

    def test_success_zip(self):
        """Test success result for ZIP format."""
        result = DesignExportResult(
            ok=True,
            format="zip",
            file_path="/tmp/design.zip",
        )
        assert result.ok is True
        assert result.format == "zip"
        assert result.file_path == "/tmp/design.zip"

    def test_success_html(self):
        """Test success result for HTML format."""
        result = DesignExportResult(
            ok=True,
            format="html",
            html_content="<html>...</html>",
        )
        assert result.ok is True
        assert result.format == "html"
        assert result.html_content == "<html>...</html>"
        assert result.file_path is None

    def test_failure(self):
        """Test failure result."""
        result = DesignExportResult(
            ok=False,
            format="pdf",
            error="LibreOffice 转换失败",
        )
        assert result.ok is False
        assert result.error == "LibreOffice 转换失败"


class TestDesignExporter:
    """Test DesignExporter class."""

    def test_export_html_format(self, tmp_path):
        """Test exporting to HTML format returns content."""
        exporter = DesignExporter()
        result = exporter.export(
            html=SAMPLE_HTML,
            output_dir=tmp_path,
            format="html",
        )
        assert result.ok is True
        assert result.format == "html"
        assert result.html_content == SAMPLE_HTML
        assert result.file_path is None

    def test_export_zip_format(self, tmp_path):
        """Test exporting to ZIP format creates archive."""
        exporter = DesignExporter()
        result = exporter.export(
            html=SAMPLE_HTML,
            output_dir=tmp_path,
            format="zip",
            filename="test_design",
        )
        assert result.ok is True
        assert result.format == "zip"
        assert result.file_path is not None

        # Verify ZIP file exists and contains index.html
        zip_path = Path(result.file_path)
        assert zip_path.exists()
        assert zip_path.suffix == ".zip"

        with zipfile.ZipFile(zip_path, "r") as zf:
            assert "index.html" in zf.namelist()
            content = zf.read("index.html").decode("utf-8")
            assert "Hello, Design!" in content

    def test_export_invalid_format(self, tmp_path):
        """Test exporting with invalid format returns error."""
        exporter = DesignExporter()
        result = exporter.export(
            html=SAMPLE_HTML,
            output_dir=tmp_path,
            format="docx",
        )
        assert result.ok is False
        assert "不支持的导出格式" in result.error

    def test_export_creates_output_dir(self, tmp_path):
        """Test that export creates output directory if missing."""
        output_dir = tmp_path / "nested" / "output"
        assert not output_dir.exists()

        exporter = DesignExporter()
        result = exporter.export(
            html=SAMPLE_HTML,
            output_dir=output_dir,
            format="html",
        )
        assert result.ok is True
        assert output_dir.exists()

    def test_export_pdf_soffice_not_found(self, tmp_path):
        """Test PDF export fallback when soffice is not installed."""
        exporter = DesignExporter()

        with (
            patch("backend.design.export._locate_soffice", return_value=None),
            patch("backend.design.export.DesignExporter._convert_with_reportlab") as mock_reportlab,
        ):
            mock_reportlab.return_value = DesignExportResult(
                ok=True,
                format="pdf",
                file_path=str(tmp_path / "design.pdf"),
            )

            result = exporter.export(
                html=SAMPLE_HTML,
                output_dir=tmp_path,
                format="pdf",
            )

            mock_reportlab.assert_called_once()
            assert result.ok is True
            assert result.format == "pdf"

    def test_export_pdf_soffice_timeout(self, tmp_path):
        """Test PDF export handles soffice timeout gracefully."""
        import subprocess

        exporter = DesignExporter()

        with (
            patch("backend.design.export._locate_soffice", return_value="/usr/bin/soffice"),
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("soffice", 10)),
            patch("backend.design.export.DesignExporter._convert_with_reportlab") as mock_reportlab,
        ):
            mock_reportlab.return_value = DesignExportResult(
                ok=False,
                format="pdf",
                error="PDF 导出失败：未找到 LibreOffice 且 reportlab 未安装",
            )

            result = exporter.export(
                html=SAMPLE_HTML,
                output_dir=tmp_path,
                format="pdf",
                timeout_seconds=10,
            )

            mock_reportlab.assert_called_once()
            assert result.format == "pdf"


class TestDesignExporterZipContent:
    """Test ZIP export content integrity."""

    def test_zip_preserves_html_content(self, tmp_path):
        """Test that ZIP export preserves the original HTML content."""
        exporter = DesignExporter()
        result = exporter.export(
            html=SAMPLE_HTML,
            output_dir=tmp_path,
            format="zip",
        )
        assert result.ok is True

        zip_path = Path(result.file_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            extracted = zf.read("index.html").decode("utf-8")
            assert extracted == SAMPLE_HTML

    def test_zip_with_custom_filename(self, tmp_path):
        """Test ZIP export with custom filename."""
        exporter = DesignExporter()
        result = exporter.export(
            html=SAMPLE_HTML,
            output_dir=tmp_path,
            format="zip",
            filename="my_custom_design",
        )
        assert result.ok is True
        assert "my_custom_design.zip" in result.file_path


class TestDesignExporterEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_html(self, tmp_path):
        """Test export with empty HTML."""
        exporter = DesignExporter()
        result = exporter.export(
            html="",
            output_dir=tmp_path,
            format="html",
        )
        assert result.ok is True
        assert result.html_content == ""

    def test_large_html(self, tmp_path):
        """Test export with large HTML content."""
        large_html = "<html><body>" + ("x" * 100000) + "</body></html>"
        exporter = DesignExporter()
        result = exporter.export(
            html=large_html,
            output_dir=tmp_path,
            format="html",
        )
        assert result.ok is True
        assert len(result.html_content) == len(large_html)

    def test_unicode_content(self, tmp_path):
        """Test export with Unicode content."""
        unicode_html = "<html><body><h1>你好世界 🌍</h1></body></html>"
        exporter = DesignExporter()

        # Test HTML format
        result = exporter.export(
            html=unicode_html,
            output_dir=tmp_path,
            format="html",
        )
        assert result.ok is True
        assert "你好世界" in result.html_content

        # Test ZIP format (should preserve Unicode)
        result = exporter.export(
            html=unicode_html,
            output_dir=tmp_path,
            format="zip",
        )
        assert result.ok is True
        with zipfile.ZipFile(result.file_path, "r") as zf:
            content = zf.read("index.html").decode("utf-8")
            assert "你好世界" in content
