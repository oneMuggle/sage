"""聊天附件上传路由

提供 POST /api/v1/chat/attachments 端点，接收音频等附件并存储到 data/media/。
r58: 附件向量索引三端点（index / search / delete）接线 r57 库层——
嵌入配置采用请求级（与 wiki ingest 同口径），索引由调用方显式触发。
"""

from __future__ import annotations

import asyncio
import logging
import re
from enum import Enum
from typing import Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# 文档提取已下沉到 services 层（聊天附件路由与文档解析子系统共用同一份
# 分发表）。以下 re-export 保持既有调用方（legacy_routes / 单测）不受影响。
from backend.services.attachment_extract import (
    EXTRACTABLE_DOC_EXTENSIONS,  # noqa: F401 — 兼容性 re-export
    MAX_ATTACHMENT_PARSE_SECONDS,  # noqa: F401 — 兼容性 re-export
    MAX_OFFICE_UNCOMPRESSED_BYTES,  # noqa: F401 — 兼容性 re-export
    MAX_OFFICE_ZIP_MEMBERS,  # noqa: F401 — 兼容性 re-export
    _extract_document_text,  # noqa: F401 — 兼容性 re-export
    _guard_office_zip_budget,  # noqa: F401 — 兼容性 re-export
    extract_attachment_text,
    extract_attachment_text_async,  # noqa: F401 — 兼容性 re-export
)
from backend.services.attachment_rag import (
    AttachmentRagError,
    attachment_vector_store_path,
    index_attachment,
    remove_attachment,
    search_attachments,
)
from backend.services.document_parse.config import load_mineru_settings
from backend.services.document_parse.factory import get_mineru_queue
from backend.services.multimodal.media_store import MEDIA_ROOT, MediaKind, MediaStore
from backend.wiki.embeddings import EmbeddingConfig

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/ogg", "audio/webm", "audio/mp4", "audio/x-m4a"}
ALLOWED_AUDIO_EXTENSIONS = {"mp3", "wav", "ogg", "webm", "m4a", "flac"}
# R37: 文本文档直传（聊天上下文注入第一切片）—— 纯 utf-8 文本可全文注入
# 2026-10-13: 扩展覆盖常见编程语言、配置、数据文件格式
ALLOWED_TEXT_TYPES = {
    "text/plain", "text/markdown", "text/csv", "text/html", "text/css",
    "text/x-python", "text/x-java-source", "text/x-go", "text/x-rust",
    "text/x-shellscript", "text/x-c", "text/x-c++", "text/x-r",
    "application/json", "application/xml", "application/x-yaml",
    "application/x-toml", "application/sql",
}
ALLOWED_TEXT_EXTENSIONS = {
    # 基础文本
    "txt", "md", "csv",
    # 编程语言
    "py", "js", "ts", "jsx", "tsx", "java", "go", "rs", "rb", "php",
    "c", "cpp", "h", "hpp", "cs", "swift", "kt", "scala", "r",
    # 前端
    "html", "css", "scss", "less", "vue", "svelte",
    # 数据/配置
    "json", "yaml", "yml", "xml", "toml", "ini", "cfg", "conf",
    # 脚本/构建
    "sh", "bash", "bat", "ps1", "sql", "makefile", "cmake", "gradle",
    # 特殊命名文件（无扩展名场景，由 legacy_routes 按 ext 匹配）
    "dockerfile", "gitignore", "properties",
    # 日志
    "log",
}
# R39 第二切片: pdf/docx/xlsx/pptx 提取文本注入 —— 白名单与发送侧提取分发表
# 必须同口径，两者共用 services.attachment_extract 的同一常量。
ALLOWED_DOC_EXTENSIONS = EXTRACTABLE_DOC_EXTENSIONS
MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 MB
#: 扩展名只允许小写字母数字，防止拼进 MediaStore 文件名时带入路径/glob 字符。
_ATTACHMENT_EXT_RE = re.compile(r"^[a-z0-9]{1,16}$")
#: 文本附件注入上下文的字符上限（R37 切片口径）
MAX_TEXT_INJECT_CHARS = 100_000
#: r58: 索引文本上限（与注入上限独立——全文索引比注入更能吃嵌入 payload）
MAX_INDEX_TEXT_CHARS = 400_000

#: r58: 附件向量库统一位置（<data>/rag/attachments.json）
ATTACHMENT_VECTOR_STORE = attachment_vector_store_path(MEDIA_ROOT.parent)


class AttachmentErrorCode(str, Enum):
    """附件上传错误码 —— 前端据此显示可读文案。"""

    UNSUPPORTED_TYPE = "unsupported_type"
    UNSUPPORTED_ENCODING = "unsupported_encoding"
    TOO_LARGE = "too_large"
    PARSE_FAILED = "parse_failed"
    PARSE_TIMEOUT = "parse_timeout"


#: 无扩展名但允许上传的文件名（小写精确匹配）。
#: 前端 CHAT_NO_EXT_FILENAMES 必须与本常量同口径。
NO_EXT_FILENAMES: frozenset[str] = frozenset({"makefile", "dockerfile"})


def _decode_text_content(content: bytes) -> Optional[str]:
    """UTF-8 → GBK → GB18030 回退解码；仍失败返回 None。"""
    for encoding in ("utf-8", "gbk", "gb18030"):
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return None


@router.post("/chat/attachments", response_model=None)
async def upload_chat_attachment(file: UploadFile = File(...)) -> dict | JSONResponse:  # noqa: PLR0911, PLR0915 — 每条早退对应一种明确的上传错误
    """上传聊天附件（音频/文本文档），存储到 data/media/ 并返回 MediaRef。

    成功: {"media_ref": {...}, "api_url": "/api/v1/media/<id>"}
    文本文档额外带 "text"（解码后全文，供聊天上下文注入）
    失败: JSONResponse(4xx/5xx, {"error_code": "...", "error": "..."})
    """
    # ── 1. 解析文件名与扩展名（含无点白名单）──────────────────────────────
    name_lower = (file.filename or "").lower()
    if "." in name_lower:
        ext = name_lower.rsplit(".", 1)[-1]
    elif name_lower in NO_EXT_FILENAMES:
        ext = name_lower  # 作为伪扩展名参与后续判定
    else:
        ext = ""

    if ext and not _ATTACHMENT_EXT_RE.fullmatch(ext):
        return JSONResponse(
            status_code=415,
            content={
                "error_code": AttachmentErrorCode.UNSUPPORTED_TYPE.value,
                "error": f"无效的文件扩展名: {ext}",
            },
        )

    # ── 2. 校验扩展名 + content-type → 415 unsupported_type ──────────────
    is_text = (file.content_type in ALLOWED_TEXT_TYPES) or (ext in ALLOWED_TEXT_EXTENSIONS)
    is_doc = ext in ALLOWED_DOC_EXTENSIONS
    is_audio = (file.content_type in ALLOWED_AUDIO_TYPES) or (ext in ALLOWED_AUDIO_EXTENSIONS)
    if not is_text and not is_doc and not is_audio:
        label = file.content_type or ext or "(无扩展名)"
        return JSONResponse(
            status_code=415,
            content={
                "error_code": AttachmentErrorCode.UNSUPPORTED_TYPE.value,
                "error": f"不支持的文件类型: {label}",
            },
        )

    # ── 3. 读内容 + 校验大小 → 413 too_large ─────────────────────────────
    content = await file.read()
    if len(content) > MAX_ATTACHMENT_SIZE:
        return JSONResponse(
            status_code=413,
            content={
                "error_code": AttachmentErrorCode.TOO_LARGE.value,
                "error": f"文件过大 ({len(content)} bytes)，上限 {MAX_ATTACHMENT_SIZE // 1024 // 1024}MB",
            },
        )

    # ── 4. 文本解码（UTF-8→GBK→GB18030）/ 文档解析 ──────────────────────
    # 全部在校验之后、save 之前 —— 失败路径不留磁盘痕迹（无孤儿文件）。
    text_content: Optional[str] = None
    if is_text:
        text_content = _decode_text_content(content)
        if text_content is None:
            return JSONResponse(
                status_code=422,
                content={
                    "error_code": AttachmentErrorCode.UNSUPPORTED_ENCODING.value,
                    "error": "文本文件编码无法识别（支持 UTF-8 / GBK / GB18030）",
                },
            )
    elif is_doc:
        try:
            text_content = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None, extract_attachment_text, content, ext
                ),
                timeout=MAX_ATTACHMENT_PARSE_SECONDS,
            )
        except asyncio.TimeoutError:  # noqa: UP041 — py3.8 上不是 builtin TimeoutError 别名
            logger.warning("attachment parse timeout: ext=%s", ext)
            return JSONResponse(
                status_code=504,
                content={
                    "error_code": AttachmentErrorCode.PARSE_TIMEOUT.value,
                    "error": "文档解析超时（文件可能过大或结构异常）",
                },
            )
        except Exception as exc:  # noqa: BLE001 — 解析器异常细节不外泄
            logger.warning(
                "attachment parse failed: ext=%s error_type=%s", ext, type(exc).__name__
            )
            return JSONResponse(
                status_code=422,
                content={
                    "error_code": AttachmentErrorCode.PARSE_FAILED.value,
                    "error": "文档解析失败（格式损坏或内容过大）",
                },
            )

    # ── 5. 全部校验通过 → store.save()（无孤儿风险）─────────────────────
    store = MediaStore(root=MEDIA_ROOT)
    ref = store.save(
        content=content,
        kind=MediaKind.DOCUMENT if (is_text or is_doc) else MediaKind.AUDIO,
        source="chat_upload",
        metadata={"original_filename": file.filename or "unknown"},
        ext=ext if ext else None,
    )
    if ext == "pdf":
        _schedule_mineru_enrichment(content, file.filename or "attachment.pdf")

    # ── 6. 构建响应 ──────────────────────────────────────────────────────
    response: dict = {"media_ref": ref, "api_url": ref.api_url}
    if text_content is not None:
        response["text"] = text_content[:MAX_TEXT_INJECT_CHARS]
    return response


def _schedule_mineru_enrichment(content: bytes, filename: str) -> None:
    """阶段 2：本地文本已返回后，后台提交 MinerU（失败静默）。"""
    try:
        settings = load_mineru_settings()
        if not (
            settings.enabled
            and settings.configured
            and settings.use_in_chat_attachment
        ):
            return
        get_mineru_queue().submit(content=content, filename=filename)
    except Exception:  # noqa: BLE001 — 双阶段补充不得影响上传响应
        logger.warning("MinerU 后台解析提交失败", exc_info=True)


def load_pdf_figure_manifest(store, media_ref, content):
    """发送侧门面：读取/构建 PDF 图表清单（调用方在线程池执行）。

    清单缓存到媒体同目录 ``<id>.figures.json``；裁图经 MediaStore 落盘。
    失败返回空列表，不阻断附件注入。
    """
    from backend.services.attachment_pdf import get_or_build_figure_manifest

    try:
        return get_or_build_figure_manifest(store, media_ref, content)
    except Exception:  # noqa: BLE001 — fail-safe：图清单不影响文本注入
        logger.exception("PDF 图表清单构建失败，跳过")
        return []


@router.get("/chat/attachments/{media_id}/text")
async def get_chat_attachment_text(media_id: str) -> dict:  # noqa: PLR0911 — 404/400/缓存命中/本地各一返回
    """R37/R39: 读取已上传文档附件的全文（txt 直读、pdf/docx/xlsx/pptx 提取）。

    聊天 producer 据此把附件内容注入上下文。非文档/不存在 → 404。
    """
    store = MediaStore(root=MEDIA_ROOT)
    loaded = await asyncio.get_running_loop().run_in_executor(None, store.load, media_id)
    if loaded is None:
        return JSONResponse(status_code=404, content={"error": f"附件不存在: {media_id}"})
    ref, content = loaded
    if ref.kind != MediaKind.DOCUMENT:
        return JSONResponse(status_code=400, content={"error": "该附件不是文本文档"})
    ext = (ref.file_path or "").rsplit(".", 1)[-1].lower() if "." in (ref.file_path or "") else "txt"
    # 阶段 2 已完成的 MinerU 解析优先（缓存按内容哈希寻址）。
    try:
        import hashlib

        from backend.services.document_parse.cache import SqliteParseCache

        cached = SqliteParseCache().get(hashlib.sha256(content).hexdigest(), "mineru")
    except Exception:  # noqa: BLE001 — 缓存不可用回退本地
        cached = None
    if cached is not None and cached.text:
        return {"media_id": media_id, "text": cached.text, "source": "mineru"}
    # 2026-10-13: 需要二进制解析的格式走 _extract_document_text，其余直读 utf-8
    try:
        text = await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(
                None, extract_attachment_text, content, ext
            ),
            timeout=MAX_ATTACHMENT_PARSE_SECONDS,
        )
        text = text[:MAX_TEXT_INJECT_CHARS]
    except asyncio.TimeoutError:  # noqa: UP041 — py3.8 上不是 builtin TimeoutError 别名
        logger.warning("attachment text extraction timeout: ext=%s", ext)
        return JSONResponse(status_code=400, content={"error": "附件解析超时"})
    except UnicodeDecodeError:
        return JSONResponse(status_code=400, content={"error": "附件不是有效的 UTF-8 文本"})
    except Exception as exc:  # noqa: BLE001 — 解析器异常细节不外泄
        logger.warning(
            "attachment text extraction failed: ext=%s error_type=%s", ext, type(exc).__name__
        )
        return JSONResponse(status_code=400, content={"error": "附件解析失败"})
    return {"media_id": media_id, "text": text, "source": "local"}


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


async def _load_document_text(
    store: MediaStore, media_id: str
) -> Tuple[Optional[str], Optional[JSONResponse]]:
    """读附件全文；err 非 None 时调用方直接把它作为响应返回。"""
    loaded = await asyncio.get_running_loop().run_in_executor(None, store.load, media_id)
    if loaded is None:
        return None, JSONResponse(status_code=404, content={"error": "附件不存在"})
    ref, content = loaded
    if ref.kind != MediaKind.DOCUMENT:
        return None, JSONResponse(status_code=400, content={"error": "该附件不是文本文档"})
    ext = (ref.file_path or "").rsplit(".", 1)[-1].lower() if "." in (ref.file_path or "") else "txt"
    # 2026-10-13: 需要二进制解析的格式走 _extract_document_text，其余直读 utf-8
    try:
        text = await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(
                None, extract_attachment_text, content, ext
            ),
            timeout=MAX_ATTACHMENT_PARSE_SECONDS,
        )
    except asyncio.TimeoutError:  # noqa: UP041 — py3.8 上不是 builtin TimeoutError 别名
        logger.warning("attachment index extraction timeout: ext=%s", ext)
        return None, JSONResponse(status_code=400, content={"error": "附件解析超时"})
    except UnicodeDecodeError:
        return None, JSONResponse(status_code=400, content={"error": "附件不是有效的 UTF-8 文本"})
    except Exception as exc:  # noqa: BLE001 — 解析器异常细节不外泄
        logger.warning(
            "attachment index extraction failed: ext=%s error_type=%s", ext, type(exc).__name__
        )
        return None, JSONResponse(status_code=400, content={"error": "附件解析失败"})
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
    text, err = await _load_document_text(store, media_id)
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
