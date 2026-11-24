"""附件文本提取：pdf/docx/xlsx/pptx → 可注入聊天上下文的纯文本。

从 ``backend/api/chat_attachment_routes.py`` 原样下沉，供聊天附件路由与
文档解析子系统（本地引擎）共用，避免维护第二份分发表。
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


# Phase 3.5：openpyxl(~460ms) + pymupdf(~300ms) + python-docx(~90ms) 只在真的
# 上传 pdf/docx/xlsx/pptx 附件时才用得上；绝大多数启动路径（会话列表 / 聊天）根本不碰
# 附件解析，这三个包留在模块顶层就是纯启动税 → 改为按需惰性导入。
def __getattr__(name: str) -> Any:
    from backend.core.lazy import load_attr, load_module

    if name == "openpyxl":
        return load_module("openpyxl", "openpyxl", globals())
    if name == "pymupdf":
        return load_module("pymupdf", "pymupdf", globals())
    if name == "_Docx":
        return load_attr("docx", "Document", globals(), alias="_Docx")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# R39 第二切片: pdf/docx/xlsx 提取文本注入（复用 office 模块既有依赖 pymupdf /
# python-docx / openpyxl，零新增依赖）
# 2026-10-13: 新增 xlsx（openpyxl 已在 Office 模块中安装）
# 2026-11-15: 新增 pptx（python-pptx 已随 Office 模块安装）
EXTRACTABLE_DOC_EXTENSIONS = frozenset({"pdf", "docx", "xlsx", "pptx"})
#: 单次附件解析墙钟上限 —— 同步解析放到线程池后，用 wait_for 防止请求挂死。
MAX_ATTACHMENT_PARSE_SECONDS = 30.0
#: docx/xlsx/pptx 是 zip 容器，解析前限制条目数与解压后总大小（zip bomb 防护）。
MAX_OFFICE_ZIP_MEMBERS = 10_000
MAX_OFFICE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024  # 100 MB
#: 文本附件解码回退链 —— UTF-8 优先, 兼容 Windows 中文 GBK / GB18030。
TEXT_DECODE_FALLBACKS = ("utf-8", "gbk", "gb18030")
CH_NL = "\n"


def decode_text_content(content: bytes) -> Optional[str]:
    """按 UTF-8 → GBK → GB18030 顺序解码文本附件；全部失败返回 None。

    上传侧(校验)、回读侧(取全文)、发送侧(注入上下文)共用此口径 ——
    否则会出现"GBK 文件能上传但读不回全文"的分裂。
    """
    for encoding in TEXT_DECODE_FALLBACKS:
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def extract_attachment_text(content: bytes, ext: str) -> str:
    """按扩展名把附件字节转成可注入聊天的文本。

    二进制文档走对应解析器；其余按 UTF-8/GBK/GB18030 回退解码。发送侧
    （legacy_routes）在线程池中调用本函数，避免再维护第二份分支。
    """
    normalized = ext.lstrip(".").lower()
    if normalized in EXTRACTABLE_DOC_EXTENSIONS:
        return _extract_document_text(content, normalized)
    text = decode_text_content(content)
    if text is None:
        raise UnicodeDecodeError(
            "utf-8", content, 0, len(content), "文本编码无法识别"
        )
    return text


async def extract_attachment_text_async(content: bytes, ext: str) -> str:
    """发送侧专用：在线程池执行提取，并施加 30s 墙钟上限。

    `wait_for` 超时只截断 await，不会强杀底层线程；线程生命周期由
    zip 预算（成员数/大小）和 25MB 上传上限共同约束。
    """
    return await asyncio.wait_for(
        asyncio.get_running_loop().run_in_executor(
            None, extract_attachment_text, content, ext
        ),
        timeout=MAX_ATTACHMENT_PARSE_SECONDS,
    )


def _extract_document_text(content: bytes, ext: str) -> str:
    """R39: pdf/docx/xlsx/pptx 提取纯文本（零新增依赖，复用 office 模块库）。

    2026-11-15: PDF 改为逐页抽取并保留 ``--- page N ---`` 页标记（模型可标注
    页码），纯图页走 office OCR 兜底（SAGE_OCR 门控）。
    """
    from backend.core.lazy import load_attr, load_module

    ext = ext.lstrip(".").lower()
    if ext in ("docx", "xlsx", "pptx"):
        _guard_office_zip_budget(content)
    if ext == "pdf":
        from backend.services.attachment_pdf import extract_pdf_pages, render_page_marked_text

        return render_page_marked_text(extract_pdf_pages(content))
    if ext == "docx":
        _Docx = load_attr("docx", "Document", globals(), alias="_Docx")
        doc = _Docx(io.BytesIO(content))
        return CH_NL.join(para.text for para in doc.paragraphs if para.text.strip())
    if ext == "xlsx":
        openpyxl = load_module("openpyxl", "openpyxl", globals())
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            sheets_text = []
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                rows = []
                for row in ws.iter_rows(values_only=True):
                    cells = [str(c) if c is not None else "" for c in row]
                    if any(cells):
                        rows.append("\t".join(cells))
                if rows:
                    sheets_text.append(f"[{sheet_name}]" + CH_NL + CH_NL.join(rows))
            return CH_NL.join(sheets_text) if sheets_text else "(empty workbook)"
        finally:
            wb.close()
    if ext == "pptx":
        return _extract_pptx_text(content)
    raise ValueError(f"unsupported document extension: {ext}")


def _extract_pptx_text(content: bytes) -> str:
    """PPTX → 文本：逐页标题 / 正文段落 / 表格单元格 / 备注。

    首版不递归组合形状（GroupShape）、图表与 SmartArt 内的文本。
    """
    from backend.core.lazy import load_attr

    Presentation = load_attr("pptx", "Presentation", globals())
    prs = Presentation(io.BytesIO(content))
    lines: List[str] = []
    for index, slide in enumerate(prs.slides, start=1):
        title = ""
        try:
            title_shape = slide.shapes.title
            if title_shape is not None and title_shape.has_text_frame:
                title = title_shape.text_frame.text.strip()
        except (AttributeError, KeyError):
            title = ""
        lines.append(f"[第{index}页]" + (f" {title}" if title else ""))
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                # 标题占位符的第一段已在页头输出；python-pptx 每次迭代
                # 都会新建 Shape 代理，不能用 id() 判断同一对象。
                try:
                    is_title_shape = bool(
                        shape.is_placeholder and shape.placeholder_format.idx == 0
                    )
                except (AttributeError, KeyError):
                    is_title_shape = False
                if is_title_shape and title:
                    continue  # 整块标题已并入页头，避免多段标题重复
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip()
                    if text:
                        lines.append(text)
            elif getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    if any(cells):
                        lines.append("\t".join(cells))
        # python-pptx 的 notes_slide getter 在缺少备注页时会新建一个 part；
        # 先看 has_notes_slide，避免对纯文本 deck 逐页产生内存副作用。
        notes = ""
        if getattr(slide, "has_notes_slide", False):
            try:
                notes_frame = slide.notes_slide.notes_text_frame
                notes = notes_frame.text.strip() if notes_frame is not None else ""
            except (AttributeError, KeyError, ValueError):
                notes = ""
        if notes:
            lines.append(f"[备注] {notes}")
    return CH_NL.join(lines)


def _guard_office_zip_budget(content: bytes) -> None:
    """拒绝解压后过大或条目过多的 Office 文件（zip bomb 防护）。

    与 backend/wiki/extract.py 的加固版同口径：先限制中央目录条目数，
    再逐条校验 file_size 非负且不超过总预算，最后校验聚合值。
    只看中央目录声明的大小，不实际解压。
    """
    import zipfile

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        members = archive.infolist()
        if len(members) > MAX_OFFICE_ZIP_MEMBERS:
            raise ValueError(f"文档条目过多: {len(members)}（上限 {MAX_OFFICE_ZIP_MEMBERS}）")
        total = 0
        for info in members:
            size = info.file_size
            if size < 0 or size > MAX_OFFICE_UNCOMPRESSED_BYTES:
                raise ValueError(f"文档成员大小非法: {size} bytes")
            total += size
            if total > MAX_OFFICE_UNCOMPRESSED_BYTES:
                raise ValueError(
                    f"文档解压后过大: {total} bytes（上限 {MAX_OFFICE_UNCOMPRESSED_BYTES}）"
                )
