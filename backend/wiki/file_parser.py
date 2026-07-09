"""多格式文档解析。

支持 PDF、DOCX、PPTX、HTML、Markdown 等格式的文本提取。
"""

import logging
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)


def parse_document(file_path: Path) -> str:
    """解析文档，提取纯文本。

    Args:
        file_path: 文件路径

    Returns:
        str: 提取的文本

    Raises:
        ValueError: 不支持的文件格式
    """
    suffix = file_path.suffix.lower()

    if suffix in (".md", ".markdown", ".txt"):
        return _parse_markdown(file_path)
    elif suffix == ".pdf":
        return _parse_pdf(file_path)
    elif suffix == ".docx":
        return _parse_docx(file_path)
    elif suffix == ".pptx":
        return _parse_pptx(file_path)
    elif suffix in (".html", ".htm"):
        return _parse_html(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {suffix}")


def _parse_markdown(file_path: Path) -> str:
    """解析 Markdown 文件。"""
    return file_path.read_text(encoding="utf-8")


def _parse_pdf(file_path: Path) -> str:
    """解析 PDF 文件。

    使用 PyPDF2 或 pdfplumber（如果可用）。
    """
    try:
        import PyPDF2

        text_parts = []
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text_parts.append(page.extract_text() or "")

        return "\n\n".join(text_parts)
    except ImportError:
        raise ImportError("PDF 解析需要 PyPDF2。请安装: pip install PyPDF2")


def _parse_docx(file_path: Path) -> str:
    """解析 DOCX 文件。

    使用 python-docx（如果可用）。
    """
    try:
        from docx import Document

        doc = Document(file_path)
        text_parts = []

        for para in doc.paragraphs:
            if para.text.strip():
                text_parts.append(para.text)

        return "\n\n".join(text_parts)
    except ImportError:
        raise ImportError("DOCX 解析需要 python-docx。请安装: pip install python-docx")


def _parse_pptx(file_path: Path) -> str:
    """解析 PPTX 文件。

    使用 python-pptx（如果可用）。
    """
    try:
        from pptx import Presentation

        prs = Presentation(file_path)
        text_parts = []

        for slide in prs.slides:
            slide_text = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    slide_text.append(shape.text)

            if slide_text:
                text_parts.append("\n".join(slide_text))

        return "\n\n".join(text_parts)
    except ImportError:
        raise ImportError("PPTX 解析需要 python-pptx。请安装: pip install python-pptx")


def _parse_html(file_path: Path) -> str:
    """解析 HTML 文件。

    使用 BeautifulSoup（如果可用）。
    """
    try:
        from bs4 import BeautifulSoup

        html = file_path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")

        # 移除 script 和 style
        for script in soup(["script", "style"]):
            script.decompose()

        return soup.get_text(separator="\n", strip=True)
    except ImportError:
        raise ImportError("HTML 解析需要 beautifulsoup4。请安装: pip install beautifulsoup4")


def extract_images(file_path: Path) -> List[Tuple[bytes, str]]:
    """从文档中提取图片。

    Args:
        file_path: 文件路径

    Returns:
        list[tuple[bytes, str]]: 图片数据和格式的列表 [(data, format), ...]
    """
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return _extract_images_pdf(file_path)
    elif suffix == ".docx":
        return _extract_images_docx(file_path)
    elif suffix == ".pptx":
        return _extract_images_pptx(file_path)
    else:
        return []


def _extract_images_pdf(file_path: Path) -> List[Tuple[bytes, str]]:
    """从 PDF 提取图片。"""
    try:
        import fitz  # PyMuPDF

        images = []
        doc = fitz.open(file_path)

        for page in doc:
            image_list = page.get_images(full=True)
            for img in image_list:
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                images.append((image_bytes, image_ext))

        doc.close()
        return images
    except ImportError:
        logger.info("PDF 图片提取需要 PyMuPDF: pip install PyMuPDF")
        return []
    except Exception as e:
        logger.warning(f"PDF 图片提取失败: {e}")
        return []


def _extract_images_docx(file_path: Path) -> List[Tuple[bytes, str]]:
    """从 DOCX 提取图片。"""
    try:
        import zipfile

        images = []
        with zipfile.ZipFile(file_path, "r") as z:
            for name in z.namelist():
                if name.startswith("word/media/"):
                    image_data = z.read(name)
                    ext = name.split(".")[-1].lower()
                    images.append((image_data, ext))

        return images
    except Exception as e:
        logger.warning(f"DOCX 图片提取失败: {e}")
        return []


def _extract_images_pptx(file_path: Path) -> List[Tuple[bytes, str]]:
    """从 PPTX 提取图片。"""
    try:
        import zipfile

        images = []
        with zipfile.ZipFile(file_path, "r") as z:
            for name in z.namelist():
                if name.startswith("ppt/media/"):
                    image_data = z.read(name)
                    ext = name.split(".")[-1].lower()
                    images.append((image_data, ext))

        return images
    except Exception as e:
        logger.warning(f"PPTX 图片提取失败: {e}")
        return []
