"""聊天附件上传路由

提供 POST /api/v1/chat/attachments 端点，接收音频等附件并存储到 data/media/。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, UploadFile

from backend.services.multimodal.media_store import MEDIA_ROOT, MediaKind, MediaStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/ogg", "audio/webm", "audio/mp4", "audio/x-m4a"}
ALLOWED_AUDIO_EXTENSIONS = {"mp3", "wav", "ogg", "webm", "m4a", "flac"}
MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 MB


@router.post("/chat/attachments")
async def upload_chat_attachment(file: UploadFile = File(...)) -> dict:
    """上传聊天附件（音频文件等），存储到 data/media/ 并返回 MediaRef

    成功: {"media_ref": {...}, "api_url": "/api/v1/media/<id>"}
    失败: {"error": "..."}
    """
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""

    if file.content_type and file.content_type not in ALLOWED_AUDIO_TYPES:
        if ext not in ALLOWED_AUDIO_EXTENSIONS:
            return {"error": f"不支持的文件类型: {file.content_type}"}

    content = await file.read()
    if len(content) > MAX_ATTACHMENT_SIZE:
        return {
            "error": f"文件过大 ({len(content)} bytes)，上限 {MAX_ATTACHMENT_SIZE // 1024 // 1024}MB"
        }

    store = MediaStore(root=MEDIA_ROOT)
    ref = store.save(
        content=content,
        kind=MediaKind.AUDIO,
        source="chat_upload",
        metadata={"original_filename": file.filename or "unknown"},
        ext=ext if ext else None,
    )
    return {"media_ref": ref, "api_url": ref.api_url}
