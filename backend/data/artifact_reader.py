# backend/data/artifact_reader.py
"""读取 artifact 文件内容并支持在文件管理器中显示。"""

from __future__ import annotations

import base64
import html as _html_mod
import subprocess
import sys
from pathlib import Path

from backend.data import artifact_repo

MAX_TEXT_BYTES = 500_000
MAX_IMAGE_BYTES = 10_000_000
#: F11 (round4 批次 D): PDF 内嵌预览上限（Chromium 内置 viewer 渲染,
#: 过大的 PDF base64 化既撑爆响应也拖垮 renderer）
MAX_PDF_BYTES = 20_000_000
#: C-2 (round5 批次 C): docx/xlsx/pptx 内嵌预览上限（同 PDF 口径）
MAX_OFFICE_BYTES = 20_000_000
#: C-2: xlsx 单 sheet 预览行数截断
MAX_SHEET_PREVIEW_ROWS = 200

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


def read_text(artifact_id: str, max_bytes: int = MAX_TEXT_BYTES) -> dict:
    """读取文本类产物内容,超长截断。"""
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None:
        return {"ok": False, "error": "artifact not found"}

    path = Path(artifact.path)
    if not path.is_file():
        return {"ok": False, "error": "file not found"}

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "error": "binary file cannot be previewed"}

    encoded = text.encode("utf-8")
    truncated = len(encoded) > max_bytes
    if truncated:
        text = encoded[:max_bytes].decode("utf-8", errors="ignore")

    return {"ok": True, "kind": artifact.kind, "content": text, "truncated": truncated}


def read_image(artifact_id: str, max_bytes: int = MAX_IMAGE_BYTES) -> dict:
    """读取图片类产物,返回 base64 data URL。"""
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None:
        return {"ok": False, "error": "artifact not found"}

    path = Path(artifact.path)
    if not path.is_file():
        return {"ok": False, "error": "file not found"}

    if path.stat().st_size > max_bytes:
        return {"ok": False, "error": "file too large"}

    mime = _IMAGE_MIME.get(path.suffix.lower(), "application/octet-stream")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"ok": True, "kind": "image", "data_url": f"data:{mime};base64,{data}"}


def read_pdf(artifact_id: str, max_bytes: int = 0) -> dict:
    """F11 (round4 批次 D): 读取 PDF 产物,返回 base64 data URL。

    前端用 iframe 内嵌 Chromium 内置 PDF viewer 渲染——浏览器原生能力,
    零新依赖。超限报错引导用户走"在文件管理器中显示"。
    ``max_bytes<=0`` 时用模块级 ``MAX_PDF_BYTES``（运行时读取,测试可覆盖）。
    """
    effective_max = max_bytes if max_bytes > 0 else MAX_PDF_BYTES
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None:
        return {"ok": False, "error": "artifact not found"}

    path = Path(artifact.path)
    if not path.is_file():
        return {"ok": False, "error": "file not found"}

    if path.stat().st_size > effective_max:
        return {"ok": False, "error": "PDF 超过 20MB 预览上限,请在文件管理器中查看"}

    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"ok": True, "kind": "pdf", "data_url": f"data:application/pdf;base64,{data}"}


def _esc(value: object) -> str:
    """HTML 文本转义（office 内容是用户数据,前端受控 innerHTML 的唯一防线）。"""
    return _html_mod.escape(str(value), quote=False)


def _docx_to_html(path: Path) -> str:
    from backend.office.word import read_docx

    result = read_docx(path)
    parts: list = []
    for para in result.paragraphs:
        text = _esc(para.text)
        if not text.strip():
            continue
        style = (para.style or "").lower()
        if style == "title":
            parts.append(f"<h2>{text}</h2>")
        elif style.startswith("heading"):
            try:
                level = min(4, max(2, int(style.rsplit(" ", 1)[-1])))
            except ValueError:
                level = 3
            parts.append(f"<h{level}>{text}</h{level}>")
        else:
            parts.append(f"<p>{text}</p>")
    for table in result.tables or []:
        rows = table.rows or []
        if not rows:
            continue
        parts.append("<table>")
        for i, row in enumerate(rows):
            cells = "".join(f"<td>{_esc(cell)}</td>" for cell in row)
            if i == 0:
                parts.append(f"<tr>{cells}</tr>")
            else:
                parts.append(f"<tr>{cells}</tr>")
        parts.append("</table>")
    return "".join(parts) or "<p>（空文档）</p>"


def _xlsx_to_html(path: Path) -> str:
    from backend.office.excel import read_xlsx

    result = read_xlsx(path)
    parts: list = []
    for sheet in result.sheets:
        parts.append(f"<h3>{_esc(sheet.name)}</h3>")
        rows = sheet.rows or []
        if not rows:
            parts.append("<p>（空表）</p>")
            continue
        parts.append("<table>")
        for row in rows[:MAX_SHEET_PREVIEW_ROWS]:
            cells = "".join(f"<td>{_esc(cell)}</td>" for cell in row)
            parts.append(f"<tr>{cells}</tr>")
        parts.append("</table>")
        if len(rows) > MAX_SHEET_PREVIEW_ROWS:
            parts.append(
                f"<p>（预览已截断,共 {len(rows)} 行）</p>"
            )
    return "".join(parts) or "<p>（空工作簿）</p>"


def _pptx_to_html(path: Path) -> str:
    from backend.office.ppt import read_ppt

    result = read_ppt(path)
    parts: list = []
    for slide in result.slides:
        title = _esc(slide.title or f"第 {slide.index} 页")
        parts.append(f"<h3>{title}</h3>")
        for block in slide.text_blocks or []:
            text = _esc(block)
            if text.strip():
                parts.append(f"<p>{text}</p>")
    return "".join(parts) or "<p>（空演示文稿）</p>"


def read_office(artifact_id: str, kind: str, max_bytes: int = 0) -> dict:
    """C-2 (round5 批次 C): docx/xlsx/pptx 产物轻量 HTML 预览。

    复用 backend/office 的 read_* 结构化读取（段落/表格/文本块）,后端生成
    **全转义** HTML——office 内容是用户数据,前端以受控 innerHTML 渲染,
    转义是唯一防线。``kind`` ∈ {"docx", "xlsx", "pptx"}。

    ``max_bytes<=0`` 时用模块级 ``MAX_OFFICE_BYTES``（运行时读取,测试可覆盖）;
    超限/解析失败返回 ok=False,引导用户走"在文件管理器中查看"。
    """
    effective_max = max_bytes if max_bytes > 0 else MAX_OFFICE_BYTES
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None:
        return {"ok": False, "error": "artifact not found"}

    path = Path(artifact.path)
    if not path.is_file():
        return {"ok": False, "error": "file not found"}

    if path.stat().st_size > effective_max:
        return {"ok": False, "error": "文件超过 20MB 预览上限,请在文件管理器中查看"}

    try:
        if kind == "docx":
            html = _docx_to_html(path)
        elif kind == "xlsx":
            html = _xlsx_to_html(path)
        elif kind == "pptx":
            html = _pptx_to_html(path)
        else:
            return {"ok": False, "error": f"unsupported office kind: {kind}"}
    except Exception as exc:  # noqa: BLE001 — 解析失败降级为不可预览
        return {"ok": False, "error": f"文件解析失败: {exc}"}

    return {"ok": True, "kind": kind, "html": html}


def reveal_in_file_manager(artifact_id: str) -> dict:
    """在系统文件管理器中显示文件(macOS/Windows/Linux)。"""
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None:
        return {"ok": False, "error": "artifact not found"}

    path = Path(artifact.path)
    if not path.is_file():
        return {"ok": False, "error": "file not found"}

    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=True)
        elif sys.platform == "win32":
            subprocess.run(["explorer", f"/select,{path}"], check=True)
        else:
            subprocess.run(["xdg-open", str(path.parent)], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return {"ok": False, "error": str(exc)}

    return {"ok": True}
