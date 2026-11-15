"""聊天附件上传路由

提供 POST /api/v1/chat/attachments 端点，接收音频等附件并存储到 data/media/。
r58: 附件向量索引三端点（index / search / delete）接线 r57 库层——
嵌入配置采用请求级（与 wiki ingest 同口径），索引由调用方显式触发。
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.office.models import _constrained_list
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
# R39 第二切片: pdf/docx/xlsx 提取文本注入（复用 office 模块既有依赖 pymupdf /
# python-docx / openpyxl，零新增依赖）
# 2026-10-13: 新增 xlsx（openpyxl 已在 Office 模块中安装）
# 2026-11-15: 新增 pptx（python-pptx 已随 Office 模块安装）
EXTRACTABLE_DOC_EXTENSIONS = frozenset({"pdf", "docx", "xlsx", "pptx"})
#: 上传白名单与发送侧提取分发表必须同口径 —— 两者共用同一常量。
ALLOWED_DOC_EXTENSIONS = EXTRACTABLE_DOC_EXTENSIONS
MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 MB
#: 单次附件解析墙钟上限 —— 同步解析放到线程池后，用 wait_for 防止请求挂死。
MAX_ATTACHMENT_PARSE_SECONDS = 30.0
#: docx/xlsx/pptx 是 zip 容器，解析前限制条目数与解压后总大小（zip bomb 防护）。
MAX_OFFICE_ZIP_MEMBERS = 10_000
MAX_OFFICE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024  # 100 MB
#: 扩展名只允许小写字母数字，防止拼进 MediaStore 文件名时带入路径/glob 字符。
_ATTACHMENT_EXT_RE = re.compile(r"^[a-z0-9]{1,16}$")
#: 文本附件注入上下文的字符上限（R37 切片口径）
MAX_TEXT_INJECT_CHARS = 100_000
#: r58: 索引文本上限（与注入上限独立——全文索引比注入更能吃嵌入 payload）
MAX_INDEX_TEXT_CHARS = 400_000
CH_NL = "\n"

#: r58: 附件向量库统一位置（<data>/rag/attachments.json）
ATTACHMENT_VECTOR_STORE = attachment_vector_store_path(MEDIA_ROOT.parent)


@router.post("/chat/attachments")
async def upload_chat_attachment(file: UploadFile = File(...)) -> dict:  # noqa: PLR0911 — 每条早退对应一种明确的上传错误
    """上传聊天附件（音频/文本文档），存储到 data/media/ 并返回 MediaRef

    成功: {"media_ref": {...}, "api_url": "/api/v1/media/<id>"}
    文本文档额外带 "text"（utf-8 解码全文，供聊天上下文注入）
    失败: {"error": "..."}
    """
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if ext and not _ATTACHMENT_EXT_RE.fullmatch(ext):
        return {"error": "无效的文件扩展名"}

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
            text = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None, extract_attachment_text, content, ext
                ),
                timeout=MAX_ATTACHMENT_PARSE_SECONDS,
            )
            response["text"] = text[:MAX_TEXT_INJECT_CHARS]
        except asyncio.TimeoutError:  # noqa: UP041 — py3.8 上不是 builtin TimeoutError 别名
            logger.warning("attachment parse timeout: ext=%s", ext)
            return {"error": "文档解析超时（文件可能过大或结构异常）"}
        except Exception as exc:  # noqa: BLE001 — 解析器异常细节不外泄
            logger.warning(
                "attachment parse failed: ext=%s error_type=%s", ext, type(exc).__name__
            )
            return {"error": "文档解析失败（格式损坏或内容过大）"}
    return response


def extract_attachment_text(content: bytes, ext: str) -> str:
    """按扩展名把附件字节转成可注入聊天的文本。

    二进制文档走对应解析器；其余按 UTF-8 文本解码。发送侧
    （legacy_routes）在线程池中调用本函数，避免再维护第二份分支。
    """
    normalized = ext.lstrip(".").lower()
    if normalized in EXTRACTABLE_DOC_EXTENSIONS:
        return _extract_document_text(content, normalized)
    return content.decode("utf-8")


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
    """R39: pdf/docx/xlsx/pptx 提取纯文本（零新增依赖，复用 office 模块库）。"""
    from backend.core.lazy import load_attr, load_module

    ext = ext.lstrip(".").lower()
    if ext in ("docx", "xlsx", "pptx"):
        _guard_office_zip_budget(content)
    if ext == "pdf":
        pymupdf = load_module("pymupdf", "pymupdf", globals())
        doc = pymupdf.open(stream=content, filetype="pdf")
        try:
            return CH_NL.join(page.get_text() for page in doc)
        finally:
            doc.close()
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


@router.get("/chat/attachments/{media_id}/text")
async def get_chat_attachment_text(media_id: str) -> dict:
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

    # _constrained_list 是仓库既有的双版本安全范式（backend/office/models.py:21）：
    # 先试 v2 的 min_length，TypeError 时回退 v1 的 min_items。
    # 裸 conlist(float, min_items=1) 在 v2 下会 TypeError（本文件有
    # `from __future__ import annotations`，注解延后到 pydantic 解析时才 eval）；
    # 而 List[float] = Field(min_items=1) 在 v2 下会被当 extra 元数据吞掉、
    # 约束静默失效。另外 conftest 的 setup_test_db 是 autouse fixture、
    # 会拉起 backend.main，所以这一处在 v2 环境下会让整个
    # backend 测试套件都起不来。
    query_vector: _constrained_list(float, min_length=1)
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
