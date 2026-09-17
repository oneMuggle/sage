"""HTML → PDF 生成路线（office-p2a）—— soffice 可用时的排版升级。

reportlab 直绘（pdf.generate_pdf 既有实现）有两个成品级缺陷：段落/
单元格**不自动换行**（长中文段落溢出页面）、表格是 shallow stub（无
边框无列宽）。本模块把结构化 pages 渲染为最小 HTML，交给 soffice
（--convert-to pdf，复用 export_pdf 的定位与进程锁）产出带自动换行
与真表格的成品。

- **HTML 内容全部 html.escape**（页面数据可能含 <、& 与用户文本）；
- soffice 缺失 / 超时 / 转换失败一律返回 False，由调用方**静默回落**
  reportlab 路线 —— 能力降级对用户不可见；
- Python 3.8 兼容（typing.* generics），可 cherry-pick 到 release/win7。
"""

from __future__ import annotations

import html
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from .export_pdf import _EXPORT_LOCK, _locate_soffice
from .models import PdfGenerateRequest

logger = logging.getLogger(__name__)

__all__ = ["render_pages_html", "generate_pdf_via_soffice"]

#: soffice HTML 转换墙钟上限（与 export_pdf 同口径）
_HTML_TIMEOUT_SECONDS = 120

#: 正文与表格的基础字号（pt）
_BODY_FONT_SIZE_PT = 12

_PAGE_SIZES_CSS = {
    "A4": "21cm 29.7cm",
    "Letter": "8.5in 11in",
    "Legal": "8.5in 14in",
}

_HTML_SHELL = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{ size: {page_size}; margin: 2.5cm 2cm; }}
  body {{ font-size: {body_pt}pt; font-family: sans-serif; }}
  h1 {{ font-size: {title_pt}pt; margin: 0 0 0.6em 0; }}
  p {{ margin: 0 0 0.55em 0; line-height: 1.5; }}
  table {{ border-collapse: collapse; margin: 0.4em 0 0.8em 0; width: 100%; }}
  td, th {{ border: 1px solid #444; padding: 3px 6px; font-size: {body_pt}pt;
            text-align: left; vertical-align: top; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=False)


def render_pages_html(req: PdfGenerateRequest) -> str:
    """把结构化 pages 渲染为完整 HTML 文档（全部字段转义）。"""
    parts: List[str] = []
    for page in req.pages:
        if page.title:
            parts.append(f"<h1>{_esc(page.title)}</h1>")
        for para in page.paragraphs:
            parts.append(f"<p>{_esc(para)}</p>")
        for table in page.tables:
            parts.append("<table>")
            for row in table:
                cells = "".join(f"<td>{_esc(cell)}</td>" for cell in row)
                parts.append(f"<tr>{cells}</tr>")
            parts.append("</table>")
    body = "\n".join(parts) or "<p></p>"
    return _HTML_SHELL.format(
        body=body,
        body_pt=_BODY_FONT_SIZE_PT,
        title_pt=16,
        page_size=_PAGE_SIZES_CSS.get(req.page_size, _PAGE_SIZES_CSS["A4"]),
    )


def generate_pdf_via_soffice(req: PdfGenerateRequest, output_path: Path) -> bool:
    """经 soffice 把 HTML 成品转成 PDF。成功返回 True；任何失败返回 False。

    调用方（pdf.generate_pdf）在本函数返回 False 时静默回落 reportlab
    直绘 —— 本函数绝不抛异常。
    """
    try:
        return _generate_inner(req, output_path)
    except Exception:  # noqa: BLE001 — 降级契约
        logger.warning("HTML→PDF generation failed; falling back to reportlab", exc_info=True)
        return False


def _generate_inner(req: PdfGenerateRequest, output_path: Path) -> bool:
    soffice_path: Optional[str] = _locate_soffice()
    if soffice_path is None:
        return False
    if output_path.exists():
        # 生成器路由层保证 output 不存在；防御性拒绝而不是覆盖。
        return False

    html_doc = render_pages_html(req)
    with tempfile.TemporaryDirectory(prefix="sage-pdf-html-") as tmp:
        html_path = Path(tmp) / "doc.html"
        html_path.write_text(html_doc, encoding="utf-8")
        with _EXPORT_LOCK:
            cmd = [
                soffice_path,
                "--headless",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                tmp,
                str(html_path),
            ]
            logger.info("Generating PDF via HTML route: %s", cmd)
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, check=False, timeout=_HTML_TIMEOUT_SECONDS
                )
            except subprocess.TimeoutExpired:
                logger.warning("HTML→PDF conversion exceeded %ss", _HTML_TIMEOUT_SECONDS)
                return False
            except OSError:
                logger.warning("soffice could not be launched for HTML route", exc_info=True)
                return False
        produced = Path(tmp) / "doc.pdf"
        if proc.returncode != 0 or not produced.is_file():
            stderr_tail = (proc.stderr or b"")[-300:].decode("utf-8", "replace").strip()
            logger.warning(
                "HTML→PDF conversion failed (exit %s): %s", proc.returncode, stderr_tail
            )
            return False
        import shutil

        shutil.copyfile(str(produced), str(output_path))
    return output_path.is_file()
