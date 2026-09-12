"""媒体文件 serve 路由

提供 GET /api/v1/media/{media_id} 端点，通过 HTTP 返回已存储的媒体文件。
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.services.multimodal.media_store import MEDIA_ROOT, MediaStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["media"])

_MEDIA_ID_RE = re.compile(r"^[0-9a-f]{12}$")


@router.get("/media/{media_id}")
async def serve_media(media_id: str) -> FileResponse:
    """提供媒体文件的 HTTP 访问

    根据 media_id 查找已存储的媒体文件并返回 FileResponse。
    - 找到: 200 + FileResponse (带 Cache-Control)
    - 未找到: 404
    """
    if not _MEDIA_ID_RE.match(media_id):
        raise HTTPException(status_code=404, detail="Media not found")
    store = MediaStore(root=MEDIA_ROOT)
    result = store.load(media_id)
    if not result:
        raise HTTPException(status_code=404, detail="Media not found")
    ref, _content = result
    abs_path = MEDIA_ROOT / ref.file_path
    # Race-condition guard: file could be deleted between load() and FileResponse
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="Media file missing on disk")
    return FileResponse(
        path=str(abs_path),
        media_type=ref.mime_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
