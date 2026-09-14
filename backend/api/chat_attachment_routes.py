"""聊天附件上传路由

提供 POST /api/v1/chat/attachments 端点，接收音频等附件并存储到 data/media/。
"""

from __future__ import annotations

import io
import logging

import pymupdf
from docx import Document as _Docx
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

from backend.services.multimodal.media_store import MEDIA_ROOT, MediaKind, MediaStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/ogg", "audio/webm", "audio/mp4", "audio/x-m4a"}
ALLOWED_AUDIO_EXTENSIONS = {"mp3", "wav", "ogg", "webm", "m4a", "flac"}
# R37: 文本文档直传（聊天上下文注入第一切片）—— 纯 utf-8 文本可全文注入
ALLOWED_TEXT_TYPES = {"text/plain", "text/markdown"}
ALLOWED_TEXT_EXTENSIONS = {"txt", "md"}
# R39 第二切片: pdf/docx 提取文本注入（复用 office 模块既有依赖 pymupdf /
# python-docx，零新增依赖）
ALLOWED_DOC_EXTENSIONS = {"pdf", "docx"}
MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 MB
#: 文本附件注入上下文的字符上限（R37 切片口径）
MAX_TEXT_INJECT_CHARS = 100_000
CH_NL = "\n"


@router.post("/chat/attachments")
async def upload_chat_attachment(file: UploadFile = File(...)) -> dict:
    """上传聊天附件（音频/文本文档），存储到 data/media/ 并返回 MediaRef

    成功: {"media_ref": {...}, "api_url": "/api/v1/media/<id>"}
    文本文档额外带 "text"（utf-8 解码全文，供聊天上下文注入）
    失败: {"error": "..."}
    """
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""

    is_text = (file.content_type in ALLOWED_TEXT_TYPES) or (ext in ALLOWED_TEXT_EXTENSIONS)
    is_doc = ext in ALLOWED_DOC_EXTENSIONS
    is_audio = (file.content_type in ALLOWED_AUDIO_TYPES) or (ext in ALLOWED_AUDIO_EXTENSIONS)
    if file.content_type and not is_text and not is_doc and not is_audio:
        return {"error": f"不支持的文件类型: {file.content_type}"}
    if not file.content_type and not is_text and not is_doc and not is_audio:
        return {"error": f"不支持的文件类型: {ext or '(无扩展名)'}"}

    content = await file.read()
    if len(content) > MAX_ATTACHMENT_SIZE:
        return {
            "error": f"文件过大 ({len(content)} bytes)，上限 {MAX_ATTACHMENT_SIZE // 1024 // 1024}MB"
        }

    store = MediaStore(root=MEDIA_ROOT)
    ref = store.save(
        content=content,
        kind=MediaKind.DOCUMENT if (is_text or is_doc) else MediaKind.AUDIO,
        source="chat_upload",
        metadata={"original_filename": file.filename or "unknown"},
        ext=ext if ext else None,
    )

    response: dict = {"media_ref": ref, "api_url": ref.api_url}
    if is_text:
        try:
            response["text"] = content.decode("utf-8")[:MAX_TEXT_INJECT_CHARS]
        except UnicodeDecodeError:
            return {"error": "文本文件不是有效的 UTF-8 编码"}
    elif is_doc:
        try:
            response["text"] = _extract_document_text(content, ext)[:MAX_TEXT_INJECT_CHARS]
        except Exception as exc:
            return {"error": f"文档解析失败: {exc}"}
    return response


def _extract_document_text(content: bytes, ext: str) -> str:
    """R39: pdf/docx 提取纯文本（零新增依赖，复用 office 模块库）。"""
    ext = ext.lstrip(".").lower()
    if ext == "pdf":
        doc = pymupdf.open(stream=content, filetype="pdf")
        try:
            return CH_NL.join(page.get_text() for page in doc)
        finally:
            doc.close()
    if ext == "docx":
        doc = _Docx(io.BytesIO(content))
        return CH_NL.join(para.text for para in doc.paragraphs if para.text.strip())
    raise ValueError(f"unsupported document extension: {ext}")


@router.get("/chat/attachments/{media_id}/text")
async def get_chat_attachment_text(media_id: str) -> dict:
    """R37/R39: 读取已上传文档附件的全文（txt 直读、pdf/docx 提取）。

    聊天 producer 据此把附件内容注入上下文。非文档/不存在 → 404。
    """
    store = MediaStore(root=MEDIA_ROOT)
    loaded = store.load(media_id)
    if loaded is None:
        return JSONResponse(status_code=404, content={"error": f"附件不存在: {media_id}"})
    ref, content = loaded
    if ref.kind != MediaKind.DOCUMENT:
        return JSONResponse(status_code=400, content={"error": "该附件不是文本文档"})
    ext = (ref.file_path or "").rsplit(".", 1)[-1].lower() if "." in (ref.file_path or "") else "txt"
    try:
        if ext == "pdf":
            text = _extract_document_text(content, "pdf")[:MAX_TEXT_INJECT_CHARS]
        elif ext == "docx":
            text = _extract_document_text(content, "docx")[:MAX_TEXT_INJECT_CHARS]
        else:
            text = content.decode("utf-8")[:MAX_TEXT_INJECT_CHARS]
    except UnicodeDecodeError:
        return JSONResponse(status_code=400, content={"error": "附件不是有效的 UTF-8 文本"})
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "附件不是有效的 UTF-8 文本"})
    return {"media_id": media_id, "text": text}
