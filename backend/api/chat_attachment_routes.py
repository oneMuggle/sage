"""聊天附件上传路由

提供 POST /api/v1/chat/attachments 端点，接收音频等附件并存储到 data/media/。
r58: 附件向量索引三端点（index / search / delete）接线 r57 库层——
嵌入配置采用请求级（与 wiki ingest 同口径），索引由调用方显式触发。
"""

from __future__ import annotations

import io
import logging
from typing import Dict, List, Optional, Tuple

import httpx
import pymupdf
from docx import Document as _Docx
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.services.attachment_rag import (
    AttachmentRagError,
    attachment_vector_store_path,
    index_attachment,
    remove_attachment,
    search_attachments,
)
from backend.services.multimodal.media_store import MEDIA_ROOT, MediaKind, MediaStore
from backend.wiki.embeddings import EmbeddingConfig

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
#: r58: 索引文本上限（与注入上限独立——全文索引比注入更能吃嵌入 payload）
MAX_INDEX_TEXT_CHARS = 400_000
CH_NL = "\n"

#: r58: 附件向量库统一位置（<data>/rag/attachments.json）
ATTACHMENT_VECTOR_STORE = attachment_vector_store_path(MEDIA_ROOT.parent)


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


# ---------- r58: 附件向量索引（接线 services/attachment_rag 库层） ----------


class AttachmentEmbedConfigIn(BaseModel):
    """请求级嵌入配置 —— 与 wiki ingest 的 embed_* 字段同口径。"""

    base_url: str = Field(min_length=1)
    api_key: str = ""
    model: str = Field(min_length=1)
    dim: int = Field(default=1536, ge=1, le=4096)


class AttachmentIndexIn(BaseModel):
    embed: AttachmentEmbedConfigIn
    target_chunk_size: int = Field(default=500, ge=50, le=4000)


class AttachmentSearchIn(BaseModel):
    """查询向量由调用方嵌入后传入——路由自身不做嵌入网络调用。"""

    query_vector: List[float] = Field(min_length=1)
    dim: int = Field(ge=1, le=4096)
    media_ids: Optional[List[str]] = None
    limit: int = Field(default=5, ge=1, le=50)


async def _embed_http_post(url: str, headers: Dict[str, str], body: dict) -> str:
    """嵌入 HTTP 客户端（wiki llm_context.http_post 同形状）。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        return resp.text


def _load_document_text(store: MediaStore, media_id: str) -> Tuple[Optional[str], Optional[JSONResponse]]:
    """读附件全文；err 非 None 时调用方直接把它作为响应返回。"""
    loaded = store.load(media_id)
    if loaded is None:
        return None, JSONResponse(status_code=404, content={"error": f"附件不存在: {media_id}"})
    ref, content = loaded
    if ref.kind != MediaKind.DOCUMENT:
        return None, JSONResponse(status_code=400, content={"error": "该附件不是文本文档"})
    ext = (ref.file_path or "").rsplit(".", 1)[-1].lower() if "." in (ref.file_path or "") else "txt"
    try:
        if ext == "pdf":
            text = _extract_document_text(content, "pdf")
        elif ext == "docx":
            text = _extract_document_text(content, "docx")
        else:
            text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None, JSONResponse(status_code=400, content={"error": "附件不是有效的 UTF-8 文本"})
    except ValueError as exc:
        return None, JSONResponse(status_code=400, content={"error": f"文档解析失败: {exc}"})
    return text, None


@router.post("/chat/attachments/search")
async def search_chat_attachments(body: AttachmentSearchIn) -> dict:
    """附件向量检索（查询向量由调用方嵌入后传入）。"""
    if len(body.query_vector) != body.dim:
        return JSONResponse(
            status_code=400,
            content={"error": f"query_vector 维度 ({len(body.query_vector)}) 与 dim ({body.dim}) 不符"},
        )
    hits = search_attachments(
        query_vector=body.query_vector,
        storage_path=ATTACHMENT_VECTOR_STORE,
        dim=body.dim,
        limit=body.limit,
        media_ids=body.media_ids,
    )
    return {
        "hits": [
            {
                "page_path": hit.page_path,
                "chunk_index": hit.chunk_index,
                "content": hit.content,
                "score": hit.score,
            }
            for hit in hits
        ]
    }


@router.post("/chat/attachments/{media_id}/index")
async def index_chat_attachment(media_id: str, body: AttachmentIndexIn) -> dict:
    """为文档附件建立向量索引（显式触发——嵌入调用花钱且慢，不挂上传钩子）。"""
    store = MediaStore(root=MEDIA_ROOT)
    text, err = _load_document_text(store, media_id)
    if err is not None:
        return err
    try:
        result = await index_attachment(
            media_id=media_id,
            text=text[:MAX_INDEX_TEXT_CHARS] if text else "",
            storage_path=ATTACHMENT_VECTOR_STORE,
            embed_config=EmbeddingConfig(
                base_url=body.embed.base_url,
                api_key=body.embed.api_key,
                model=body.embed.model,
                dim=body.embed.dim,
            ),
            http_post=_embed_http_post,
            target_chunk_size=body.target_chunk_size,
        )
    except AttachmentRagError as exc:
        logger.warning("附件索引失败: %s %s", media_id, exc)
        return JSONResponse(status_code=502, content={"error": str(exc)})
    return {
        "media_id": result.media_id,
        "chunks": result.chunks,
        "dim": result.dim,
        "page_path": result.page_path,
    }


@router.delete("/chat/attachments/{media_id}/index")
async def delete_chat_attachment_index(media_id: str) -> dict:
    """删除附件的向量索引（幂等：未索引 → removed=0）。"""
    removed = remove_attachment(media_id=media_id, storage_path=ATTACHMENT_VECTOR_STORE)
    return {"media_id": media_id, "removed": removed}
