"""聊天附件上传路由

提供 POST /api/v1/chat/attachments 端点，接收音频等附件并存储到 data/media/。
"""

from __future__ import annotations

import logging

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
MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 MB
#: 文本附件注入上下文的字符上限（R37 切片口径）
MAX_TEXT_INJECT_CHARS = 100_000


@router.post("/chat/attachments")
async def upload_chat_attachment(file: UploadFile = File(...)) -> dict:
    """上传聊天附件（音频/文本文档），存储到 data/media/ 并返回 MediaRef

    成功: {"media_ref": {...}, "api_url": "/api/v1/media/<id>"}
    文本文档额外带 "text"（utf-8 解码全文，供聊天上下文注入）
    失败: {"error": "..."}
    """
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""

    is_text = (file.content_type in ALLOWED_TEXT_TYPES) or (ext in ALLOWED_TEXT_EXTENSIONS)
    is_audio = (file.content_type in ALLOWED_AUDIO_TYPES) or (ext in ALLOWED_AUDIO_EXTENSIONS)
    if file.content_type and not is_text and not is_audio:
        return {"error": f"不支持的文件类型: {file.content_type}"}
    if not file.content_type and not is_text and not is_audio:
        return {"error": f"不支持的文件类型: {ext or '(无扩展名)'}"}

    content = await file.read()
    if len(content) > MAX_ATTACHMENT_SIZE:
        return {
            "error": f"文件过大 ({len(content)} bytes)，上限 {MAX_ATTACHMENT_SIZE // 1024 // 1024}MB"
        }

    store = MediaStore(root=MEDIA_ROOT)
    ref = store.save(
        content=content,
        kind=MediaKind.DOCUMENT if is_text else MediaKind.AUDIO,
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
    return response


@router.get("/chat/attachments/{media_id}/text")
async def get_chat_attachment_text(media_id: str) -> dict:
    """R37: 读取已上传文本文档的全文（utf-8，截断到注入上限）。

    聊天 producer 据此把附件内容注入上下文。非文本/不存在 → 404。
    """
    store = MediaStore(root=MEDIA_ROOT)
    loaded = store.load(media_id)
    if loaded is None:
        return JSONResponse(status_code=404, content={"error": f"附件不存在: {media_id}"})
    ref, content = loaded
    if ref.kind != MediaKind.DOCUMENT:
        return JSONResponse(status_code=400, content={"error": "该附件不是文本文档"})
    try:
        return {"media_id": media_id, "text": content.decode("utf-8")[:MAX_TEXT_INJECT_CHARS]}
    except UnicodeDecodeError:
        return JSONResponse(status_code=400, content={"error": "附件不是有效的 UTF-8 文本"})
